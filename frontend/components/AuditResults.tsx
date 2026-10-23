/* eslint-disable @next/next/no-img-element */
"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
    type AuditResponse,
    type AIPlanResponse,
    type AhrefsOffpageResponse,
    type AIRewriteResponse,
    type AIRewriteScoreResponse,
    getDimensionDisplayName,
    apiClient,
} from "@/lib/api";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";
import { StatTile } from "./ui/stat-tile";

export function formatMarketInWords(market?: string | null): string {
    if (!market) return "";
    const m = market.trim().toLowerCase();
    const map: Record<string, string> = {
        "us/en": "United States, English",
        "es/es": "Spain, Spanish",
        "gb/en": "United Kingdom, English",
        "uk/en": "United Kingdom, English",
        "mx/es": "Mexico, Spanish",
        "ca/en": "Canada, English",
        "ca/fr": "Canada, French",
        "au/en": "Australia, English",
        "fr/fr": "France, French",
        "de/de": "Germany, German",
        "it/it": "Italy, Italian",
        "br/pt": "Brazil, Portuguese",
    };
    if (map[m]) return map[m];
    if (market.includes("/")) {
        const parts = market.split("/");
        const countryCode = parts[0]?.toUpperCase() || "";
        const langCode = parts[1]?.toLowerCase() || "";
        const countryMap: Record<string, string> = {
            US: "United States",
            ES: "Spain",
            GB: "United Kingdom",
            UK: "United Kingdom",
            MX: "Mexico",
            CA: "Canada",
            AU: "Australia",
            FR: "France",
            DE: "Germany",
            IT: "Italy",
            BR: "Brazil",
            AR: "Argentina",
            CO: "Colombia",
            CL: "Chile",
        };
        const langMap: Record<string, string> = {
            en: "English",
            es: "Spanish",
            fr: "French",
            de: "German",
            it: "Italian",
            pt: "Portuguese",
        };
        const country = countryMap[countryCode] || countryCode;
        const lang = langMap[langCode] || langCode;
        return `${country}, ${lang}`;
    }
    return market;
}

const EXCLUDED_TECHNICAL_DIMENSIONS = new Set([
    "technical_infrastructure",
    "metadata_schema",
]);

const EXCLUDED_SUBMETRIC_KEYWORDS = [
    "https",
    "render",
    "crawl",
    "bot",
    "speed",
    "schema",
];

const FRIENDLY_SUBMETRIC_NAMES: Record<string, string> = {
    "Rule of 60 (Answer First)": "Answer First in Intro",
    "Interrogative H2s": "Question-based Headings",
    "Heading Hierarchy": "Heading Structure",
    "Power Lead (Entity in Lead)": "Main Topic in Opening Sentence",
    "Lexical Richness (MTLD)": "Vocabulary Variety",
    "Autonomous Passages": "Self-contained Sections",
    "Complete Sentences": "Complete Sentences",
    "Content Depth": "Content Depth & Substance",
    "Evidence Density": "Facts & Evidence Density",
    "Numeric Specificity": "Specific Data & Figures",
    "Attribution Signals": "Source Attributions",
    "Author Signals": "Author Information",
    "Freshness Signals": "Publication & Update Dates",
    "Formatting Citability": "Scannable Formatting",
    "Links Verifiability": "Source Links & Citations",
    "Direct Answers": "Direct Answers",
    "Query Relevance": "Search Query Relevance",
    "Keyword Coverage": "Topic Coverage",
    "Entity Identification": "Clear Key Entities",
    "Trust Pages": "About & Editorial Policy",
};

interface TopAction {
    friendlyName: string;
    submetricName: string;
    recommendation: string;
    impact: number;
    rawScore: number;
}

interface AuditResultsProps {
    results: AuditResponse;
    originalText?: string;
    hideAiFixes?: boolean;
}

export default function AuditResults({ results, originalText, hideAiFixes = false }: AuditResultsProps) {
    const [activeTab, setActiveTab] = useState<"overview" | "dimensions" | "ai_plan">("overview");
    const [openDimensions, setOpenDimensions] = useState<Record<string, boolean>>({});

    const [isPlanLoading, setIsPlanLoading] = useState(false);
    const [isBriefDownloading, setIsBriefDownloading] = useState(false);
    const [customQuery, setCustomQuery] = useState("");
    const [isEditingQuery, setIsEditingQuery] = useState(false);
    const [aiPlan, setAiPlan] = useState<AIPlanResponse | null>(null);
    const [aiPlanError, setAiPlanError] = useState<string | null>(null);
    const [copiedSources, setCopiedSources] = useState(false);

    // Ahrefs Off-page state
    const [ahrefsEnabled, setAhrefsEnabled] = useState(false);
    const [isAhrefsLoading, setIsAhrefsLoading] = useState(false);
    const [ahrefsData, setAhrefsData] = useState<AhrefsOffpageResponse | null>(null);
    const [ahrefsError, setAhrefsError] = useState<string | null>(null);

    // AI Rewrite state
    const [isRewriting, setIsRewriting] = useState(false);
    const [rewriteDraft, setRewriteDraft] = useState<AIRewriteResponse | null>(null);
    const [rewriteScore, setRewriteScore] = useState<AIRewriteScoreResponse | null>(null);
    const [rewriteError, setRewriteError] = useState<string | null>(null);
    const [rewriteScoreError, setRewriteScoreError] = useState<string | null>(null);
    const [draftDownloadError, setDraftDownloadError] = useState<string | null>(null);
    const [showOriginalText, setShowOriginalText] = useState(false);
    const [copiedMarkdown, setCopiedMarkdown] = useState(false);
    const [copiedHtml, setCopiedHtml] = useState(false);
    const [isDraftDownloading, setIsDraftDownloading] = useState(false);
    const hasDraftContent = Boolean(rewriteDraft?.draft_markdown && rewriteDraft.draft_markdown.trim().length > 0);

    useEffect(() => {
        apiClient.getVersion().then((v) => {
            if (v && v.ahrefs_enabled) {
                setAhrefsEnabled(true);
            }
        }).catch(() => {});
    }, []);

    // Calculate Top 5 Actions
    const topActions = useMemo<TopAction[]>(() => {
        const candidates: TopAction[] = [];
        if (!results.detector_results) return candidates;

        for (const det of results.detector_results) {
            if (EXCLUDED_TECHNICAL_DIMENSIONS.has(det.dimension)) continue;
            const detWeight = det.weight != null ? det.weight : 0.10;
            const breakdowns = det.breakdown || [];

            for (const b of breakdowns) {
                const rawScore = b.raw_score != null ? b.raw_score : 100.0;
                const nameLower = (b.name || "").toLowerCase();
                if (EXCLUDED_SUBMETRIC_KEYWORDS.some(kw => nameLower.includes(kw))) continue;
                if (rawScore >= 70.0) continue;

                const validRecs = (b.recommendations || []).map(r => r.trim()).filter(Boolean);
                if (validRecs.length === 0) continue;

                const impact = detWeight * (100.0 - rawScore);
                const friendlyName = FRIENDLY_SUBMETRIC_NAMES[b.name] || b.name;
                candidates.push({
                    friendlyName,
                    submetricName: b.name,
                    recommendation: validRecs[0],
                    impact,
                    rawScore,
                });
            }
        }

        // Merge Heading Structure and Text Walls if both are among candidates
        const headingIndex = candidates.findIndex(c => c.friendlyName === "Heading Structure" || c.submetricName === "Heading Structure");
        const textWallsIndex = candidates.findIndex(c => c.friendlyName === "Text Walls" || c.submetricName === "Text Walls");

        let filtered = candidates;
        if (headingIndex !== -1 && textWallsIndex !== -1) {
            const headingCand = candidates[headingIndex];
            const textWallsCand = candidates[textWallsIndex];
            const mergedAction: TopAction = {
                friendlyName: "Add H2 headings to break up the text",
                submetricName: "Heading Structure",
                recommendation: headingCand.recommendation,
                impact: Math.max(headingCand.impact, textWallsCand.impact),
                rawScore: Math.min(headingCand.rawScore, textWallsCand.rawScore),
            };
            filtered = candidates.filter((_, idx) => idx !== headingIndex && idx !== textWallsIndex);
            filtered.push(mergedAction);
        }

        filtered.sort((a, b) => b.impact - a.impact);
        return filtered.slice(0, 5);
    }, [results]);

    const handleToggleDimension = (dimKey: string) => {
        setOpenDimensions(prev => ({
            ...prev,
            [dimKey]: !prev[dimKey],
        }));
    };

    const handleExpandAllDimensions = () => {
        const allOpen: Record<string, boolean> = {};
        results.detector_results.forEach(d => {
            allOpen[d.dimension] = true;
        });
        setOpenDimensions(allOpen);
    };

    const handleCollapseAllDimensions = () => {
        setOpenDimensions({});
    };

    const handleCheckAhrefs = async () => {
        if (!results.url) return;
        setIsAhrefsLoading(true);
        setAhrefsError(null);
        try {
            const data = await apiClient.checkOffpage(results.url, results.language || "en");
            setAhrefsData(data);
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to fetch Ahrefs data";
            setAhrefsError(errorMsg);
        } finally {
            setIsAhrefsLoading(false);
        }
    };

    const handleGenerateAIPlan = async (overrideQuery?: string) => {
        if (!results.ai_context) return;
        setIsPlanLoading(true);
        setAiPlanError(null);
        try {
            const data = await apiClient.generateAIPlan(results.ai_context, overrideQuery);
            setAiPlan(data);
            if (data.serp_query) {
                setCustomQuery(data.serp_query);
            }
            setIsEditingQuery(false);
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to generate AI plan";
            setAiPlanError(errorMsg);
        } finally {
            setIsPlanLoading(false);
        }
    };

    const handleRewriteArticle = async () => {
        if (!results.ai_context || !aiPlan) return;
        setIsRewriting(true);
        setRewriteError(null);
        setRewriteScoreError(null);
        setDraftDownloadError(null);
        try {
            const rewriteResp = await apiClient.rewriteArticle({
                ai_context: results.ai_context,
                ai_plan: aiPlan,
                target_query: customQuery || undefined,
            });
            setRewriteDraft(rewriteResp);

            // Audit & score rewrite
            const origHtml = results.ai_context.main_html || `<p>${results.ai_context.main_text || ""}</p>`;
            try {
                const scoreResp = await apiClient.scoreRewrite({
                    original_html: origHtml,
                    draft_markdown: rewriteResp.draft_markdown,
                    target_query: customQuery || undefined,
                });
                setRewriteScore(scoreResp);
                setRewriteScoreError(null);
            } catch (scoreErr) {
                console.error("Failed to calculate score comparison:", scoreErr);
                const scoreMsg = scoreErr instanceof Error ? scoreErr.message : "Failed to calculate score comparison";
                setRewriteScoreError(scoreMsg);
                setRewriteScore(null);
            }
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to generate rewrite draft";
            setRewriteError(errorMsg);
            setRewriteDraft(null);
            setRewriteScore(null);
            setRewriteScoreError(null);
        } finally {
            setIsRewriting(false);
        }
    };

    const handleCopyRewriteMarkdown = () => {
        if (!rewriteDraft?.draft_markdown) return;
        navigator.clipboard.writeText(rewriteDraft.draft_markdown);
        setCopiedMarkdown(true);
        setTimeout(() => setCopiedMarkdown(false), 2000);
    };

    const handleCopyRewriteHtml = () => {
        if (!rewriteDraft?.draft_markdown) return;
        // Simple client-side Markdown to clean HTML conversion
        const escapeHtml = (s: string) =>
            s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        const formatText = (raw: string) => {
            const styleRe = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;
            let res = "";
            let prev = 0;
            let sm: RegExpExecArray | null;
            while ((sm = styleRe.exec(raw)) !== null) {
                res += escapeHtml(raw.slice(prev, sm.index));
                const matchStr = sm[0];
                if (matchStr.startsWith('**') && matchStr.endsWith('**') && matchStr.length >= 4) {
                    res += `<strong>${escapeHtml(matchStr.slice(2, -2))}</strong>`;
                } else if (matchStr.startsWith('*') && matchStr.endsWith('*') && matchStr.length >= 2) {
                    res += `<em>${escapeHtml(matchStr.slice(1, -1))}</em>`;
                } else {
                    res += escapeHtml(matchStr);
                }
                prev = sm.index + matchStr.length;
            }
            return res + escapeHtml(raw.slice(prev));
        };
        // Converts inline Markdown images, links, bold and italic to HTML; everything else is escaped
        const inline = (s: string) => {
            const tokenRe = /(!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)|\[([^\]]*)\]\((https?:\/\/[^)\s]+)\))/g;
            let out = "";
            let last = 0;
            let m: RegExpExecArray | null;
            while ((m = tokenRe.exec(s)) !== null) {
                out += formatText(s.slice(last, m.index));
                if (m[0].startsWith('!')) {
                    out += `<img src="${escapeHtml(m[3])}" alt="${escapeHtml(m[2])}" />`;
                } else {
                    out += `<a href="${escapeHtml(m[5])}">${escapeHtml(m[4] || m[5])}</a>`;
                }
                last = m.index + m[0].length;
            }
            return out + formatText(s.slice(last));
        };
        const lines = rewriteDraft.draft_markdown.split('\n');
        const htmlParts: string[] = [];
        let inTable = false;
        let tableHeaderDone = false;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            if (line.startsWith('|') && line.endsWith('|')) {
                if (!inTable) {
                    inTable = true;
                    tableHeaderDone = false;
                    htmlParts.push('<table border="1" style="border-collapse: collapse; width: 100%;">');
                }
                const cells = line.slice(1, -1).split('|').map(c => c.trim());
                if (cells.every(c => /^:?-+:?$/.test(c))) {
                    tableHeaderDone = true;
                    continue;
                }
                if (!tableHeaderDone) {
                    htmlParts.push(`  <thead><tr>${cells.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>`);
                    tableHeaderDone = true;
                } else {
                    htmlParts.push(`  <tr>${cells.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`);
                }
                continue;
            } else if (inTable) {
                inTable = false;
                htmlParts.push('</tbody></table>');
            }

            if (!line) continue;

            const imgLineMatch = line.match(/^!\[([^\]]*)\]\((https?:\/\/[^)\s]+)(?:\s+"[^"]*")?\)$/);
            if (imgLineMatch) {
                htmlParts.push(`<p><img src="${escapeHtml(imgLineMatch[2])}" alt="${escapeHtml(imgLineMatch[1])}" /></p>`);
                continue;
            }

            if (line.startsWith('# ')) {
                htmlParts.push(`<h1>${inline(line.slice(2))}</h1>`);
            } else if (line.startsWith('## ')) {
                htmlParts.push(`<h2>${inline(line.slice(3))}</h2>`);
            } else if (line.startsWith('### ')) {
                htmlParts.push(`<h3>${inline(line.slice(4))}</h3>`);
            } else if (line.startsWith('- ')) {
                htmlParts.push(`<li>${inline(line.slice(2))}</li>`);
            } else {
                htmlParts.push(`<p>${inline(line)}</p>`);
            }
        }
        if (inTable) {
            htmlParts.push('</tbody></table>');
        }

        navigator.clipboard.writeText(htmlParts.join('\n'));
        setCopiedHtml(true);
        setTimeout(() => setCopiedHtml(false), 2000);
    };

    const handleDownloadRewriteDocx = async () => {
        if (!rewriteDraft?.draft_markdown?.trim()) return;
        setIsDraftDownloading(true);
        setDraftDownloadError(null);
        try {
            await apiClient.downloadRewriteDraft({
                url: results.url,
                draft_markdown: rewriteDraft.draft_markdown,
                warnings: rewriteDraft.warnings || [],
                score_comparison: rewriteScore,
            });
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Failed to download Word document";
            setDraftDownloadError(msg);
        } finally {
            setIsDraftDownloading(false);
        }
    };

    const handleDownloadEditorBrief = async () => {
        setIsBriefDownloading(true);
        try {
            await apiClient.downloadEditorBrief({
                audit_result: results,
                ai_plan: aiPlan,
                ahrefs_offpage: ahrefsData,
            });
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to download improvement report";
            alert(`Error downloading report: ${errorMsg}`);
        } finally {
            setIsBriefDownloading(false);
        }
    };

    const handleCopyLeadParagraph = () => {
        if (!aiPlan?.suggested_lead?.suggested) return;
        navigator.clipboard.writeText(aiPlan.suggested_lead.suggested);
        alert("Suggested lead paragraph copied to clipboard!");
    };

    const handleCopyCombinedSchema = () => {
        if (!aiPlan?.combined_schema) return;
        navigator.clipboard.writeText(JSON.stringify(aiPlan.combined_schema, null, 2));
        alert("Combined Schema.org copied to clipboard!");
    };

    const handleCopySources = () => {
        if (!aiPlan?.sources_to_cite || aiPlan.sources_to_cite.length === 0) return;
        const text = aiPlan.sources_to_cite.map((s, i) =>
            `${i + 1}. ${s.title} (${s.domain}) - ${s.url}\n   Found in: ${s.found_in}\n   Why: ${s.why}`
        ).join("\n\n");
        navigator.clipboard.writeText(text);
        setCopiedSources(true);
        setTimeout(() => setCopiedSources(false), 2000);
    };

    const handleCopyTableHtml = () => {
        if (!aiPlan?.suggested_table?.headers || !aiPlan?.suggested_table?.rows) return;
        const { title, headers, rows } = aiPlan.suggested_table;
        const html = [
            `<table>`,
            `  <caption>${title}</caption>`,
            `  <thead>`,
            `    <tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>`,
            `  </thead>`,
            `  <tbody>`,
            ...rows.map(row => `    <tr>${row.map(c => `<td>${c}</td>`).join('')}</tr>`),
            `  </tbody>`,
            `</table>`
        ].join('\n');
        navigator.clipboard.writeText(html);
        alert("Table HTML copied to clipboard!");
    };

    const handleCopyPlanMarkdown = () => {
        if (!aiPlan) return;
        const lines: string[] = [];
        lines.push(`# Content Improvement Plan: ${results.url || results.ai_context?.title || 'Audited Page'}\n`);
        if (aiPlan.serp_used && aiPlan.serp_query) {
            const marketWords = formatMarketInWords(aiPlan.serp_market);
            const marketPart = marketWords ? ` (${marketWords})` : "";
            const paaCount = aiPlan.serp_paa_found ?? 0;
            lines.push(`> Google data used: search '${aiPlan.serp_query}'${marketPart} · ${paaCount} real Google questions found · sources listed below\n`);
        }

        if (aiPlan.warnings && aiPlan.warnings.length > 0) {
            lines.push(`## Warnings & Recommendations`);
            aiPlan.warnings.forEach(w => lines.push(`- ⚠️ ${w}`));
            lines.push("");
        }

        if (aiPlan.suggested_lead) {
            lines.push(`## Suggested Opening Paragraph`);
            lines.push(`*Rewrite the opening paragraph to answer the primary topic immediately (inverted pyramid structure).*\n`);
            if (aiPlan.suggested_lead.original) {
                lines.push(`**Current Text:**\n${aiPlan.suggested_lead.original}\n`);
            }
            lines.push(`**Suggested Optimized Opening:**\n${aiPlan.suggested_lead.suggested}\n`);
            if (aiPlan.suggested_lead.rationale) {
                lines.push(`*Rationale:* ${aiPlan.suggested_lead.rationale}\n`);
            }
        }

        if (aiPlan.inconsistencies && aiPlan.inconsistencies.length > 0) {
            lines.push(`## Inconsistencies Found on the Page`);
            lines.push(`*The page contradicts itself here. Pick one version and use it everywhere, so AI engines extract a single answer.*\n`);
            aiPlan.inconsistencies.forEach((inc, i) => {
                lines.push(`### ${i + 1}. ${inc.issue}`);
                lines.push(`- **Conflicting Values:** ${inc.values.map(v => `\`"${v}"\``).join(" vs ")}`);
                lines.push(`- **Recommendation:** ${inc.suggestion}\n`);
            });
        }

        if (aiPlan.questions_to_answer && aiPlan.questions_to_answer.length > 0) {
            lines.push(`## Questions Your Page Should Answer`);
            lines.push(`*Add these as an FAQ block. Short, direct answers are what AI engines quote.*\n`);
            aiPlan.questions_to_answer.forEach((q, i) => {
                const srcBadge = q.answer_source === "page" ? "[Info already on the page — rewrite it as a Q&A]" : "[Missing from the page — needs new content]";
                const paaBadge = q.origin === "google_paa" ? " [Real Google question]" : "";
                lines.push(`### ${i + 1}. ${q.question} ${srcBadge}${paaBadge}`);
                lines.push(`${q.draft_answer}\n`);
            });
        }

        if (aiPlan.suggested_h2_structure && aiPlan.suggested_h2_structure.length > 0) {
            lines.push(`## Suggested H2 Structure`);
            lines.push(`*Use these headings to organise the page. 'Already on the page' means keep it as is. 'Exists — add the heading' means the topic is discussed but needs an H2. 'New' means the section has to be written.*\n`);
            aiPlan.suggested_h2_structure.forEach((h, i) => {
                const statusBadge = h.status === "present"
                    ? "[Already on the page — keep it]"
                    : h.status === "rename"
                    ? `[Already on the page — consider renaming to: ${h.h2}]`
                    : h.status === "existing"
                    ? "[Exists — add the heading]"
                    : "[New — write this section]";
                lines.push(`- **H2 ${i + 1}: ${h.h2}** ${statusBadge}`);
                lines.push(`  - *Purpose:* ${h.purpose}`);
            });
            lines.push("");
        }

        if (aiPlan.suggested_table) {
            lines.push(`## Suggested Table: ${aiPlan.suggested_table.title}`);
            lines.push(`*Add this table to the page. All values come from the page itself.*\n`);
            if (aiPlan.suggested_table.headers && aiPlan.suggested_table.rows) {
                lines.push(`| ${aiPlan.suggested_table.headers.join(" | ")} |`);
                lines.push(`| ${aiPlan.suggested_table.headers.map(() => "---").join(" | ")} |`);
                aiPlan.suggested_table.rows.forEach(r => {
                    lines.push(`| ${r.join(" | ")} |`);
                });
                lines.push("");
            } else if (aiPlan.suggested_table.table_idea) {
                lines.push(`*Table Idea:* ${aiPlan.suggested_table.table_idea}\n`);
            }
        }

        if (aiPlan.data_opportunities && aiPlan.data_opportunities.length > 0) {
            lines.push(`## Data that Would Enrich the Text`);
            lines.push(`*Information worth adding. No figures are suggested: find them in the type of source shown.*\n`);
            aiPlan.data_opportunities.forEach(d => {
                lines.push(`- **${d.suggestion}** (Recommended Source: ${d.source_type})`);
            });
            lines.push("");
        }

        if (aiPlan.sources_to_cite && aiPlan.sources_to_cite.length > 0) {
            lines.push(`## Sources to Cite or Link`);
            lines.push(`*Real pages that Google ranks or cites for this topic. Link or cite the relevant ones.*\n`);
            aiPlan.sources_to_cite.forEach((s, i) => {
                lines.push(`${i + 1}. [${s.title}](${s.url}) - Domain: ${s.domain} (${s.found_in})`);
                if (s.why) {
                    lines.push(`   - *Why:* ${s.why}`);
                }
            });
            lines.push("");
        }

        if (aiPlan.paragraphs_to_add && aiPlan.paragraphs_to_add.length > 0) {
            lines.push(`## Paragraphs to Add`);
            lines.push(`*Ready-to-paste paragraphs, written only with facts from the page.*\n`);
            aiPlan.paragraphs_to_add.forEach((p, i) => {
                lines.push(`### Paragraph ${i + 1}: Addressing "${p.target_issue}"`);
                lines.push(`*Placement:* ${p.placement}\n`);
                lines.push(`> ${p.suggested_text}\n`);
            });
        }

        if (aiPlan.combined_schema) {
            lines.push(`## Combined Schema.org JSON-LD`);
            lines.push(`*For the developer: paste in the page <head>.*\n`);
            lines.push("```json");
            lines.push(JSON.stringify(aiPlan.combined_schema, null, 2));
            lines.push("```\n");
        }

        lines.push(`---\n*Disclaimer: AI-generated suggestions. Review before publishing. They do not affect the Citation Score.*`);

        navigator.clipboard.writeText(lines.join("\n"));
        alert("Full improvement plan copied as Markdown!");
    };

    const handleCopySummary = () => {
        const criticalIssues = results.detector_results
            .filter(d => d.score < 50)
            .sort((a, b) => a.score - b.score)
            .slice(0, 3)
            .map(d => getDimensionDisplayName(d.dimension));

        const allRecs = results.detector_results
            .flatMap(d => d.breakdown)
            .flatMap(b => b.recommendations);

        const uniqueRecs = Array.from(new Set(allRecs)).slice(0, 3);

        const report = [
            `🚀 GEO Audit Report: ${results.url || "Text Content"}`,
            `📉 Score: ${results.total_score.toFixed(0)}/100`,
            `🚨 Top Critical Issues:`,
            criticalIssues.length > 0
                ? criticalIssues.map((issue, i) => `${i + 1}. ${issue}`).join('\n')
                : "None! Great job.",
            `✅ Quick Wins:`,
            uniqueRecs.length > 0
                ? uniqueRecs.map(rec => `- ${rec}`).join('\n')
                : "- No immediate recommendations."
        ].join('\n');

        navigator.clipboard.writeText(report);
        alert("Executive Summary copied to clipboard!");
    };

    return (
        <div className="space-y-6 animate-fade-in">
            {/* Persistent Export Bar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 bg-surface border border-hairline rounded-card shadow-card no-print">
                <div className="flex flex-wrap items-center gap-2">
                    <button
                        type="button"
                        onClick={handleCopySummary}
                        className="btn-default text-xs h-8 px-3 flex items-center gap-2 cursor-pointer font-medium"
                    >
                        <span>📋</span>
                        <span>Copy Summary for Slack</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => window.print()}
                        className="btn-default text-xs h-8 px-3 flex items-center gap-2 cursor-pointer font-medium"
                    >
                        <span>🖨️</span>
                        <span>Print PDF</span>
                    </button>
                </div>
                <div className="flex flex-wrap items-center gap-2.5">
                    <button
                        type="button"
                        onClick={handleDownloadEditorBrief}
                        disabled={isBriefDownloading}
                        className="btn-primary text-xs h-8 px-3.5 flex items-center gap-2 cursor-pointer font-medium"
                    >
                        {isBriefDownloading ? (
                            <>
                                <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full" />
                                <span>Generating .docx...</span>
                            </>
                        ) : (
                            <>
                                <span>📄</span>
                                <span>Download improvement report (.docx)</span>
                            </>
                        )}
                    </button>
                    {(aiPlan || ahrefsData) && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                            {aiPlan && (
                                <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface-2 border border-hairline text-ink-2 font-medium">
                                    Includes AI recommendations
                                </span>
                            )}
                            {ahrefsData && (
                                <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface-2 border border-hairline text-ink-2 font-medium">
                                    Includes Ahrefs data
                                </span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Tab Navigation Switcher */}
            <div className="flex items-center gap-2 border-b border-hairline pb-3 no-print">
                <button
                    type="button"
                    onClick={() => setActiveTab("overview")}
                    className={`px-4 py-2 rounded-control text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 select-none ${
                        activeTab === "overview"
                            ? "bg-ink text-surface shadow-sm"
                            : "text-ink-2 hover:text-ink hover:bg-surface-2"
                    }`}
                >
                    <span>📊</span>
                    <span>Overview</span>
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab("dimensions")}
                    className={`px-4 py-2 rounded-control text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 select-none ${
                        activeTab === "dimensions"
                            ? "bg-ink text-surface shadow-sm"
                            : "text-ink-2 hover:text-ink hover:bg-surface-2"
                    }`}
                >
                    <span>📑</span>
                    <span>Dimensions</span>
                    <span className={`text-micro px-1.5 py-0.2 rounded-full font-mono font-bold ${
                        activeTab === "dimensions" ? "bg-surface text-ink" : "bg-surface-2 text-ink-2 border border-hairline"
                    }`}>
                        {results.detector_results.length}
                    </span>
                </button>
                {!hideAiFixes && results.ai_context && (
                    <button
                        type="button"
                        onClick={() => setActiveTab("ai_plan")}
                        className={`px-4 py-2 rounded-control text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 select-none ${
                            activeTab === "ai_plan"
                                ? "bg-ink text-surface shadow-sm"
                                : "text-ink-2 hover:text-ink hover:bg-surface-2"
                        }`}
                    >
                        <span>✨</span>
                        <span>AI Plan</span>
                        {aiPlan && (
                            <span className="size-2 rounded-full bg-accent animate-pulse" />
                        )}
                    </button>
                )}
            </div>

            {/* TAB 1: OVERVIEW */}
            <div className={`space-y-6 ${activeTab === "overview" ? "block" : "hidden print:block"}`}>
                {/* Score & Meta Card */}
                <div className="rounded-card border border-hairline bg-surface p-6 sm:p-8">
                    <div className="flex flex-col lg:flex-row items-center gap-8">
                        {/* Score Circle */}
                        <div className="flex flex-col items-center shrink-0">
                            <ScoreDisplay
                                score={results.total_score}
                                label="Citation Score"
                                sublabel="Measures on-page readiness for AI citation. Off-page factors like organic rankings and brand authority are not included."
                            />
                            {results.score_capped && (
                                <div className="mt-3 px-3 py-2 rounded-lg bg-critical-soft border border-critical/30 text-critical text-xs font-medium text-center max-w-xs">
                                    ⚠️ Score capped at 30: {results.cap_reason}
                                </div>
                            )}
                        </div>

                        {/* Metadata & Actions */}
                        <div className="flex-1 text-center lg:text-left min-w-0">
                            <div className="flex flex-col justify-between items-start gap-3">
                                <div className="w-full">
                                    <div className="flex items-center gap-2 justify-center lg:justify-start flex-wrap mb-1">
                                        <h2 className="text-xl sm:text-2xl font-bold text-ink tracking-tight">
                                            Audit Overview
                                        </h2>
                                        <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-surface-2 text-ink-2 border border-hairline">
                                            {results.scoring_version}
                                        </span>
                                    </div>
                                    <p
                                        title={results.url || results.ai_context?.title || "Direct Text Submission"}
                                        className="text-xs sm:text-sm text-ink-3 mb-2 truncate max-w-2xl"
                                    >
                                        {results.url || results.ai_context?.title || "Direct Text Submission"}
                                    </p>
                                </div>
                            </div>

                            {/* Details meta footer */}
                            <div className="flex flex-wrap gap-4 justify-center lg:justify-start text-xs text-ink-3 mt-6 pt-4 border-t border-hairline font-medium">
                                <span className="flex items-center gap-1.5">
                                    <span>⏱️</span> {(results.analysis_time_ms / 1000).toFixed(2)}s
                                </span>
                                <span className="flex items-center gap-1.5">
                                    <span>🌐</span> {(results.language || "en").toUpperCase()}
                                </span>
                                <span className="flex items-center gap-1.5">
                                    <span>📄</span> {results.content_type === "news" ? "News / Press" : results.content_type === "review" ? "Review" : results.content_type === "product" ? "Product" : "Guide / Blog"}
                                </span>
                                <span className="flex items-center gap-1.5">
                                    <span>📅</span> {new Date(results.analyzed_at).toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" })}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Top 5 Actions Card */}
                <div className="rounded-card border border-hairline bg-surface p-6">
                    <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-critical-soft text-critical flex items-center justify-center text-sm font-bold shadow-2xs">
                                ⚡
                            </div>
                            <div>
                                <h3 className="text-base font-bold text-ink tracking-tight">
                                    Top 5 Actions
                                </h3>
                                <p className="text-xs text-ink-3">
                                    Highest-impact non-technical fixes to improve citability
                                </p>
                            </div>
                        </div>
                    </div>

                    {topActions.length === 0 ? (
                        <div className="p-4 bg-good-soft border border-good/30 rounded-xl text-good text-xs flex items-center gap-2">
                            <span>✓</span>
                            <span>All non-technical content scored 70 or higher. No critical editorial weaknesses found!</span>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {topActions.map((action, idx) => (
                                <div
                                    key={idx}
                                    className="p-4 bg-surface-2/60 border border-hairline rounded-xl flex flex-col sm:flex-row sm:items-start justify-between gap-3 transition-all hover:bg-surface-2"
                                >
                                    <div className="space-y-1.5 flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="w-5 h-5 rounded-full bg-ink text-white text-xs font-bold flex items-center justify-center shrink-0">
                                                {idx + 1}
                                            </span>
                                            <span className="text-sm font-bold text-ink">
                                                {action.friendlyName}
                                            </span>
                                            <span className="text-[11px] font-bold font-mono px-2 py-0.5 rounded bg-critical-soft text-critical border-critical/30">
                                                Score: {Math.round(action.rawScore)}/100
                                            </span>
                                        </div>
                                        <p className="text-xs text-ink-2 pl-7 leading-relaxed">
                                            {action.recommendation}
                                        </p>
                                    </div>
                                    <div className="sm:text-right shrink-0 pl-7 sm:pl-0">
                                        <span className="text-ink-3 font-mono text-xs">
                                            Impact: {action.impact.toFixed(1)}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Off-page Signals (Ahrefs) Card */}
                {results.url && (
                    <div className="rounded-card border border-hairline bg-surface p-6">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                            <div className="flex items-center gap-2.5">
                                <div className="w-8 h-8 rounded-lg bg-orange-100 text-orange-700 flex items-center justify-center text-sm font-bold shadow-2xs">
                                    🔗
                                </div>
                                <div>
                                    <h3 className="text-base font-bold text-ink tracking-tight">
                                        Off-page Signals (Ahrefs)
                                    </h3>
                                    <p className="text-xs text-ink-3">
                                        External backlink, authority, and ranking indicators
                                    </p>
                                </div>
                            </div>

                            {ahrefsEnabled && (
                                <button
                                    type="button"
                                    onClick={handleCheckAhrefs}
                                    disabled={isAhrefsLoading}
                                    className="text-xs px-3.5 py-2 bg-surface hover:bg-surface-2 border border-hairline rounded-xl text-ink-2 shadow-2xs transition-all flex items-center gap-2 cursor-pointer font-medium no-print"
                                >
                                    {isAhrefsLoading ? (
                                        <>
                                            <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-ink border-t-transparent rounded-full" />
                                            <span>Fetching Ahrefs...</span>
                                        </>
                                    ) : (
                                        <>
                                            <span>🔍</span>
                                            <span>{ahrefsData ? "Refresh Ahrefs Data" : "Check Ahrefs Signals"}</span>
                                        </>
                                    )}
                                </button>
                            )}
                        </div>

                        {!ahrefsEnabled && (
                            <p className="text-xs text-ink-3">
                                Ahrefs integration is disabled. Set <code className="font-mono text-[11px] bg-surface-2 px-1 py-0.5 rounded text-ink-2">GEO_AUDITOR_AHREFS_API_KEY</code> to enable live authority and backlink metrics.
                            </p>
                        )}

                        {ahrefsError && (
                            <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-critical mt-2 flex items-center justify-between gap-2">
                                <span>⚠️ {ahrefsError}</span>
                                <button
                                    type="button"
                                    onClick={handleCheckAhrefs}
                                    disabled={isAhrefsLoading}
                                    className="underline text-critical font-semibold cursor-pointer"
                                >
                                    Retry
                                </button>
                            </div>
                        )}

                        {ahrefsData && (
                            <div className="space-y-4 mt-3">
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Domain Rating</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.domain_rating != null ? ahrefsData.domain_rating : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">URL Rating</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.url_rating != null ? ahrefsData.url_rating : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Referring Domains</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.referring_domains != null ? ahrefsData.referring_domains.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Backlinks</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.backlinks != null ? ahrefsData.backlinks.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Organic Keywords</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.organic_keywords != null ? ahrefsData.organic_keywords.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Top 3 Keywords</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.top3_keywords != null ? ahrefsData.top3_keywords.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-surface-2 border border-hairline sm:col-span-2">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Organic Traffic/Month</p>
                                        <p className="text-xl font-bold font-mono text-ink mt-0.5">
                                            {ahrefsData.organic_traffic != null ? Math.round(ahrefsData.organic_traffic).toLocaleString() : "—"}
                                        </p>
                                    </div>
                                </div>

                                {/* Who links to this page */}
                                <div className="pt-2">
                                    <p className="text-xs font-bold text-ink-2 mb-2 uppercase tracking-wider">
                                        Who links to this page
                                    </p>
                                    {ahrefsData.linking_pages === null ? (
                                        <p className="text-xs text-ink-3 italic py-1">Link list unavailable.</p>
                                    ) : ahrefsData.linking_pages.length === 0 ? (
                                        <p className="text-xs text-ink-3 italic py-1">
                                            {ahrefsData.referring_domains && ahrefsData.referring_domains > 0
                                                ? `Ahrefs counts ${ahrefsData.referring_domains} referring ${ahrefsData.referring_domains === 1 ? "domain" : "domains"}, but none returned a live link right now (the link may have been removed recently).`
                                                : "No live links found."}
                                        </p>
                                    ) : (
                                        <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
                                            <table className="w-full text-left text-xs">
                                                <thead className="bg-surface-2 border-b border-hairline text-ink-2 font-semibold">
                                                    <tr>
                                                        <th className="px-3 py-2.5">Domain</th>
                                                        <th className="px-3 py-2.5">DR</th>
                                                        <th className="px-3 py-2.5">Linking page</th>
                                                        <th className="px-3 py-2.5">Anchor</th>
                                                        <th className="px-3 py-2.5">Type</th>
                                                        <th className="px-3 py-2.5">First seen</th>
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-slate-100 text-ink-2">
                                                    {ahrefsData.linking_pages.map((link, idx) => (
                                                        <tr key={idx} className={link.spam ? "bg-red-50/50" : "hover:bg-surface-2/50"}>
                                                            <td className="px-3 py-2 font-medium text-ink whitespace-nowrap">
                                                                <div className="flex items-center gap-1.5">
                                                                    <span>{link.domain}</span>
                                                                    {link.spam && (
                                                                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-critical-soft text-critical border border-red-200">
                                                                            Spam
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            </td>
                                                            <td className="px-3 py-2 font-mono text-ink">
                                                                {link.domain_rating != null ? link.domain_rating : "—"}
                                                            </td>
                                                            <td className="px-3 py-2 max-w-[200px] truncate">
                                                                <a
                                                                    href={link.url_from}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    className="text-accent hover:underline truncate block"
                                                                    title={link.url_from}
                                                                >
                                                                    {link.url_from}
                                                                </a>
                                                            </td>
                                                            <td className="px-3 py-2 max-w-[160px] truncate text-ink-2" title={link.anchor}>
                                                                {link.anchor || <span className="text-ink-3 italic">No anchor</span>}
                                                            </td>
                                                            <td className="px-3 py-2 whitespace-nowrap">
                                                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                                                                    link.dofollow
                                                                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                                                        : "bg-surface-2 text-ink-2 border border-hairline"
                                                                }`}>
                                                                    {link.dofollow ? "Dofollow" : "Nofollow"}
                                                                </span>
                                                            </td>
                                                            <td className="px-3 py-2 whitespace-nowrap text-ink-3 font-mono text-[11px]">
                                                                {link.first_seen || "—"}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    )}
                                </div>

                                {/* Recommendations */}
                                {ahrefsData.recommendations && ahrefsData.recommendations.length > 0 && (
                                    <div className="pt-2">
                                        <p className="text-xs font-bold text-ink-2 mb-2 uppercase tracking-wider">
                                            Off-page Recommendations:
                                        </p>
                                        <ul className="space-y-1.5 text-xs text-ink-2">
                                            {ahrefsData.recommendations.map((rec, idx) => (
                                                <li key={idx} className="flex items-start gap-2 bg-surface-2 p-2.5 rounded-lg border border-hairline leading-relaxed">
                                                    <span className="text-orange-500 font-bold">→</span>
                                                    <span>{rec}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Not Measured by this Tool Card */}
                <div className="rounded-card border border-hairline bg-surface p-6">
                    <div className="flex items-center gap-2.5 mb-2">
                        <div className="w-8 h-8 rounded-lg bg-surface-2 text-ink-2 flex items-center justify-center text-sm font-bold shadow-2xs">
                            ℹ️
                        </div>
                        <h4 className="text-base font-bold text-ink tracking-tight">
                            Not measured by this tool
                        </h4>
                    </div>
                    {ahrefsData && (
                        <p className="text-xs text-emerald-700 font-medium mb-3 flex items-center gap-1.5">
                            <span>✓</span> Partially covered above with Ahrefs data.
                        </p>
                    )}
                    <p className="text-xs text-ink-3 mb-4 leading-relaxed">
                        The Citation Score measures on-page architectural and content readiness. Leading AI engines (ChatGPT, Perplexity, Gemini) also consider external signals:
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-surface-2 border border-hairline">
                            <span className="text-lg">📊</span>
                            <div>
                                <p className="font-semibold text-ink text-xs">Organic ranking position</p>
                                <p className="text-[11px] text-ink-3">Domain authority & traditional search ranking</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-surface-2 border border-hairline">
                            <span className="text-lg">🏷️</span>
                            <div>
                                <p className="font-semibold text-ink text-xs">Brand mentions on third-party sites</p>
                                <p className="text-[11px] text-ink-3">Unlinked co-citations and web consensus</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-surface-2 border border-hairline">
                            <span className="text-lg">📱</span>
                            <div>
                                <p className="font-semibold text-ink text-xs">Presence on YouTube / Reddit / social</p>
                                <p className="text-[11px] text-ink-3">Community discussion and multimedia footprints</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-surface-2 border border-hairline">
                            <span className="text-lg">🏛️</span>
                            <div>
                                <p className="font-semibold text-ink text-xs">Publisher reputation</p>
                                <p className="text-[11px] text-ink-3">Historical accuracy & verified entity graph status</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* TAB 2: DIMENSIONS */}
            <div className={`space-y-4 ${activeTab === "dimensions" ? "block" : "hidden print:block"}`}>
                <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
                    <div>
                        <h3 className="text-base sm:text-lg font-bold text-ink tracking-tight">
                            Citability Dimensions ({results.detector_results.length})
                        </h3>
                        <p className="text-xs text-ink-3">
                            Click any dimension to expand submetrics, explanations, and evidence
                        </p>
                    </div>

                    <div className="flex items-center gap-2 no-print">
                        <button
                            type="button"
                            onClick={handleExpandAllDimensions}
                            className="text-xs px-3 py-1.5 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer"
                        >
                            Expand All
                        </button>
                        <button
                            type="button"
                            onClick={handleCollapseAllDimensions}
                            className="text-xs px-3 py-1.5 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer"
                        >
                            Collapse All
                        </button>
                    </div>
                </div>

                <div className="space-y-3">
                    {results.detector_results.map((result, index) => (
                        <ScoreBreakdown
                            key={index}
                            result={result}
                            isOpen={openDimensions[result.dimension]}
                            onToggle={() => handleToggleDimension(result.dimension)}
                        />
                    ))}
                </div>
            </div>

            {/* TAB 3: AI PLAN */}
            {!hideAiFixes && results.ai_context && (
                <div className={`space-y-6 ${activeTab === "ai_plan" ? "block" : "hidden print:block"}`}>
                    {/* Header info card */}
                    <div className="rounded-card border border-hairline bg-surface p-6 border-hairline">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                            <div>
                                <div className="flex items-center gap-2">
                                    <span className="text-xl">✨</span>
                                    <h3 className="text-lg font-bold text-ink tracking-tight">
                                        AI Suggested Fixes &amp; Content Plan
                                    </h3>
                                </div>
                                <p className="text-xs text-ink-3 mt-1 max-w-xl">
                                    Generated with the Chiliz AI model and live Google data. Figures and links are checked against the page and Google results. Review before publishing.
                                </p>
                            </div>

                            <div className="flex flex-wrap gap-2.5 no-print">
                                <button
                                    type="button"
                                    onClick={() => handleGenerateAIPlan()}
                                    disabled={isPlanLoading}
                                    className="btn-primary text-xs px-4 py-2 flex items-center gap-2"
                                >
                                    {isPlanLoading ? (
                                        <>
                                            <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full" />
                                            <span>Generating with AI… this can take a few minutes.</span>
                                        </>
                                    ) : (
                                        <>
                                            <span>✨</span>
                                            <span>Generate AI recommendations</span>
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Empty State when plan not generated yet */}
                    {!aiPlan && !isPlanLoading && !aiPlanError && (
                        <div className="rounded-card border border-hairline bg-surface p-10 text-center space-y-4">
                            <div className="w-12 h-12 mx-auto rounded-2xl bg-red-50 text-accent flex items-center justify-center text-2xl font-bold shadow-2xs">
                                ✨
                            </div>
                            <div className="max-w-md mx-auto space-y-2">
                                <h4 className="text-base font-bold text-ink">
                                    Generate AI Recommendations
                                </h4>
                                <p className="text-xs text-ink-3 leading-relaxed">
                                    Generate actionable AI recommendations including an optimized opening paragraph, Schema.org JSON-LD, and a full content improvement plan (Google PAA questions, heading hierarchy, comparison table, content opportunities, and authoritative sources to cite).
                                </p>
                                <div className="pt-2">
                                    <button
                                        type="button"
                                        onClick={() => handleGenerateAIPlan()}
                                        className="btn-primary text-xs px-4 py-2 inline-flex items-center gap-2"
                                    >
                                        <span>✨</span>
                                        <span>Generate AI recommendations</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Full Plan Error Notice with Retry */}
                    {aiPlanError && (
                        <div className="rounded-card border border-hairline bg-surface p-4 border-warn/30 bg-warn-soft/50">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                <div className="flex items-center gap-2 text-xs text-warn font-medium">
                                    <span>⚠️</span>
                                    <span>AI recommendations could not be generated: {aiPlanError}</span>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => handleGenerateAIPlan(customQuery || undefined)}
                                    disabled={isPlanLoading}
                                    className="text-xs px-3.5 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium rounded-xl shadow-2xs transition-all cursor-pointer whitespace-nowrap self-start sm:self-auto"
                                >
                                    {isPlanLoading ? "Retrying..." : "Retry"}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Full Improvement Plan Output */}
                    {aiPlan && (
                        <div className="rounded-card border border-hairline bg-surface p-6 space-y-6">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-hairline">
                                <div>
                                    <h4 className="text-base font-bold text-ink flex items-center gap-2">
                                        <span>📋</span> Full Improvement Plan
                                    </h4>
                                    {(aiPlan.serp_used || aiPlan.serp_query || aiPlan.warnings?.some(w => w.toLowerCase().includes("google data unavailable"))) && (
                                        <div className="space-y-1.5 mt-1">
                                            <p className="text-xs text-ink-3">
                                                {aiPlan.serp_used && aiPlan.serp_query ? (
                                                    <>Google data used: search &apos;{aiPlan.serp_query}&apos;{aiPlan.serp_market ? ` (${formatMarketInWords(aiPlan.serp_market)})` : ""} · {aiPlan.serp_paa_found ?? 0} real Google questions found · sources listed below</>
                                                ) : (
                                                    <>Search query: &apos;{aiPlan.serp_query || customQuery || "Auto"}&apos;{aiPlan.serp_market ? ` (${formatMarketInWords(aiPlan.serp_market)})` : ""}</>
                                                )}
                                                {" "}
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setIsEditingQuery(!isEditingQuery);
                                                        if (!customQuery) setCustomQuery(aiPlan.serp_query || "");
                                                    }}
                                                    className="text-xs text-accent hover:text-critical underline font-medium ml-1 transition-colors cursor-pointer"
                                                >
                                                    {isEditingQuery ? "Cancel" : "Change search"}
                                                </button>
                                            </p>
                                            {isEditingQuery && (
                                                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 pt-1">
                                                    <input
                                                        type="text"
                                                        value={customQuery}
                                                        onChange={(e) => setCustomQuery(e.target.value)}
                                                        placeholder="Custom Google search query..."
                                                        className="input-field text-xs py-1.5 w-full sm:w-80"
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => handleGenerateAIPlan(customQuery)}
                                                        disabled={isPlanLoading || !customQuery.trim()}
                                                        className="btn-primary text-xs px-3.5 py-1.5 shrink-0"
                                                    >
                                                        {isPlanLoading ? (
                                                            <>
                                                                <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                                                                Regenerating...
                                                            </>
                                                        ) : (
                                                            "Regenerate plan"
                                                        )}
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                <div className="flex items-center gap-2 no-print shrink-0 self-start sm:self-auto">
                                    <button
                                        type="button"
                                        onClick={handleCopyPlanMarkdown}
                                        className="text-xs px-3 py-1.5 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1.5"
                                    >
                                        <span>📥</span>
                                        <span>Copy plan as Markdown</span>
                                    </button>
                                </div>
                            </div>

                            {/* Suggested opening paragraph */}
                            {aiPlan.suggested_lead && (
                                <div className="space-y-3 pb-6 border-b border-hairline">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h5 className="text-xs font-bold text-ink-2 uppercase tracking-wider">
                                                Suggested opening paragraph
                                            </h5>
                                            <p className="text-xs text-ink-3 mt-0.5">
                                                Rewrite the opening paragraph to answer the primary topic immediately (inverted pyramid structure).
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleCopyLeadParagraph}
                                            className="text-xs px-2.5 py-1 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                        >
                                            📋 Copy Suggested Text
                                        </button>
                                    </div>

                                    {aiPlan.suggested_lead.rationale && (
                                        <p className="text-xs text-ink-3 italic">
                                            {aiPlan.suggested_lead.rationale}
                                        </p>
                                    )}

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div className="p-4 bg-surface-2 border border-hairline rounded-xl space-y-1.5">
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-ink-3">
                                                Current Text
                                            </span>
                                            <p className="text-xs text-ink-2 leading-relaxed font-mono">
                                                {aiPlan.suggested_lead.original || "(Empty or undetected lead)"}
                                            </p>
                                        </div>
                                        <div className="p-4 bg-emerald-50/50 border border-emerald-200/80 rounded-xl space-y-1.5">
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                                                Suggested Optimized Opening
                                            </span>
                                            <p className="text-xs text-ink leading-relaxed font-mono font-medium">
                                                {aiPlan.suggested_lead.suggested}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Warnings */}
                            {aiPlan.warnings && aiPlan.warnings.length > 0 && (
                                <div className="p-3.5 bg-amber-50 border border-warn/30 rounded-xl space-y-2">
                                    <div className="text-xs font-semibold text-amber-900 flex items-center gap-1.5">
                                        <span>⚠️</span> Warnings &amp; Actions Required:
                                    </div>
                                    <ul className="text-xs text-warn list-disc list-inside space-y-2 pl-1">
                                        {aiPlan.warnings.map((w, idx) => {
                                            const isGoogleUnavailable = w.toLowerCase().includes("google data unavailable");
                                            return (
                                                <li key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                                    <span>{w}</span>
                                                    {isGoogleUnavailable && (
                                                        <button
                                                            type="button"
                                                            onClick={() => handleGenerateAIPlan(customQuery || aiPlan.serp_query || undefined)}
                                                            disabled={isPlanLoading}
                                                            className="text-xs px-3 py-1 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium rounded-lg shadow-2xs transition-all cursor-pointer whitespace-nowrap self-start sm:self-auto shrink-0 flex items-center gap-1.5"
                                                        >
                                                            {isPlanLoading ? (
                                                                <>
                                                                    <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                                                                    <span>Retrying...</span>
                                                                </>
                                                            ) : (
                                                                <span>Retry with Google data</span>
                                                            )}
                                                        </button>
                                                    )}
                                                </li>
                                            );
                                        })}
                                    </ul>
                                </div>
                            )}

                            {/* Inconsistencies found on the page */}
                            {aiPlan.inconsistencies && aiPlan.inconsistencies.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                            <span>⚖️ Inconsistencies found on the page</span>
                                            <span className="text-xs font-normal text-ink-3">({aiPlan.inconsistencies.length})</span>
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-0.5">
                                            The page contradicts itself here. Pick one version and use it everywhere, so AI engines extract a single answer.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.inconsistencies.map((inc, i) => (
                                            <div key={i} className="p-3.5 rounded-xl bg-amber-50/60 border border-warn/30 space-y-2 text-xs">
                                                <div className="font-semibold text-amber-900 flex items-center gap-1.5">
                                                    <span>🔍</span> {inc.issue}
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-[11px] text-ink-3 uppercase tracking-wider font-medium">Conflicting values:</span>
                                                    {inc.values.map((val, vIdx) => (
                                                        <span key={vIdx} className="px-2 py-0.5 rounded bg-surface text-rose-700 border border-rose-200 font-mono text-[11px]">
                                                            &ldquo;{val}&rdquo;
                                                        </span>
                                                    ))}
                                                </div>
                                                <div className="p-2.5 rounded-lg bg-surface/80 border border-hairline text-ink-2">
                                                    <strong className="text-ink">Recommendation: </strong>
                                                    {inc.suggestion}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Questions your page should answer */}
                            {aiPlan.questions_to_answer && aiPlan.questions_to_answer.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                            <span>❓ Questions your page should answer</span>
                                            <span className="text-xs font-normal text-ink-3">({aiPlan.questions_to_answer.length})</span>
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-0.5">
                                            Add these as an FAQ block. Short, direct answers are what AI engines quote.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.questions_to_answer.map((q, i) => (
                                            <div key={i} className="p-3.5 rounded-xl bg-surface-2 border border-hairline space-y-2">
                                                <div className="flex items-start justify-between gap-2 flex-wrap">
                                                    <div className="text-xs font-semibold text-ink">
                                                        {q.question}
                                                    </div>
                                                    <div className="flex items-center gap-1.5 shrink-0">
                                                        {q.origin === "google_paa" && (
                                                            <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-blue-50 border border-blue-200 text-blue-700">
                                                                Real Google question
                                                            </span>
                                                        )}
                                                        <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded ${
                                                            q.answer_source === "page"
                                                                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                                                                : "bg-amber-50 border border-warn/30 text-warn"
                                                        }`}>
                                                            {q.answer_source === "page"
                                                                ? "Info already on the page — rewrite it as a Q&A"
                                                                : "Missing from the page — needs new content"}
                                                        </span>
                                                    </div>
                                                </div>
                                                <div className="text-xs text-ink-2 leading-relaxed bg-surface p-2.5 rounded-lg border border-hairline">
                                                    {(() => {
                                                        const parts = q.draft_answer.split(/(\[EDITOR:[^\]]*\])/);
                                                        return parts.map((part, pIdx) => {
                                                            if (part.startsWith("[EDITOR:") && part.endsWith("]")) {
                                                                return (
                                                                    <span
                                                                        key={pIdx}
                                                                        className="font-medium bg-warn-soft border border-warn/30 text-warn px-1.5 py-0.5 rounded mx-0.5 inline-block"
                                                                    >
                                                                        {part}
                                                                    </span>
                                                                );
                                                            }
                                                            return <span key={pIdx}>{part}</span>;
                                                        });
                                                    })()}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Suggested H2 structure */}
                            {aiPlan.suggested_h2_structure && aiPlan.suggested_h2_structure.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                            <span>📑 Suggested H2 structure</span>
                                            <span className="text-xs font-normal text-ink-3">({aiPlan.suggested_h2_structure.length})</span>
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-0.5">
                                            Use these headings to organise the page. &apos;Already on the page&apos; means keep it as is. &apos;Exists — add the heading&apos; means the topic is discussed but needs an H2. &apos;New&apos; means the section has to be written.
                                        </p>
                                    </div>
                                    <div className="divide-y divide-hairline rounded-xl border border-hairline overflow-hidden bg-surface">
                                        {aiPlan.suggested_h2_structure.map((item, idx) => (
                                            <div key={idx} className="p-3.5 flex items-start justify-between gap-3 text-xs">
                                                <div className="space-y-1">
                                                    <div className="font-semibold text-ink">
                                                        {item.h2}
                                                    </div>
                                                    <div className="text-ink-3 text-[11px]">
                                                        {item.purpose}
                                                    </div>
                                                </div>
                                                <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded shrink-0 ${
                                                    item.status === "present"
                                                        ? "bg-good-soft border border-good/30 text-good"
                                                        : item.status === "rename"
                                                        ? "bg-amber-500/10 border border-amber-500/30 text-amber-600 dark:text-amber-400"
                                                        : item.status === "existing"
                                                        ? "bg-surface-2 text-ink-2 border border-hairline"
                                                        : "bg-critical-soft border border-critical/30 text-critical"
                                                }`}>
                                                    {item.status === "present"
                                                        ? "Already on the page — keep it"
                                                        : item.status === "rename"
                                                        ? `Already on the page — consider renaming to: ${item.h2}`
                                                        : item.status === "existing"
                                                        ? "Exists — add the heading"
                                                        : "New — write this section"}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Suggested table */}
                            {aiPlan.suggested_table && (
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                                <span>📊 Suggested table: {aiPlan.suggested_table.title}</span>
                                            </h4>
                                            <p className="text-xs text-ink-3 mt-0.5">
                                                Add this table to the page. All values come from the page itself.
                                            </p>
                                        </div>
                                        {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows && (
                                            <button
                                                type="button"
                                                onClick={handleCopyTableHtml}
                                                className="text-xs px-2.5 py-1 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                            >
                                                📋 Copy HTML
                                            </button>
                                        )}
                                    </div>
                                    {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows ? (
                                        <div className="overflow-x-auto border border-hairline rounded-xl">
                                            <table className="w-full text-left text-xs">
                                                <thead className="bg-surface-2 border-b border-hairline text-ink-2 font-semibold">
                                                    <tr>
                                                        {aiPlan.suggested_table.headers.map((h, idx) => (
                                                            <th key={idx} className="py-2.5 px-3">{h}</th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-slate-100">
                                                    {aiPlan.suggested_table.rows.map((row, rIdx) => (
                                                        <tr key={rIdx} className="hover:bg-surface-2/50">
                                                            {row.map((cell, cIdx) => (
                                                                <td key={cIdx} className="py-2.5 px-3 text-ink-2">{cell}</td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <p className="text-xs text-ink-2 italic bg-surface-2 p-3 rounded-lg border border-hairline">
                                            {aiPlan.suggested_table.table_idea}
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* Data that would enrich the text */}
                            {aiPlan.data_opportunities && aiPlan.data_opportunities.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                            <span>💡 Data that would enrich the text</span>
                                            <span className="text-xs font-normal text-ink-3">({aiPlan.data_opportunities.length})</span>
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-0.5">
                                            Information worth adding. No figures are suggested: find them in the type of source shown.
                                        </p>
                                    </div>
                                    <div className="grid gap-2.5">
                                        {aiPlan.data_opportunities.map((item, idx) => (
                                            <div key={idx} className="p-3 rounded-xl bg-surface-2 border border-hairline flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                                                <span className="text-ink">{item.suggestion}</span>
                                                <span className="text-[11px] px-2 py-0.5 rounded bg-surface text-ink-2 border border-hairline shrink-0 self-start sm:self-auto font-mono">
                                                    Source: {item.source_type}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Sources to cite or link */}
                            {aiPlan.sources_to_cite && aiPlan.sources_to_cite.length > 0 && (
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between gap-2">
                                        <div>
                                            <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                                <span>🔗 Sources to cite or link</span>
                                                <span className="text-xs font-normal text-ink-3">({aiPlan.sources_to_cite.length})</span>
                                            </h4>
                                            <p className="text-xs text-ink-3 mt-0.5">
                                                Real pages that Google ranks or cites for this topic. Link or cite the relevant ones.
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleCopySources}
                                            className="text-xs px-2.5 py-1 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1 shrink-0"
                                        >
                                            {copiedSources ? "✓ Copied" : "📋 Copy list"}
                                        </button>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.sources_to_cite.map((src, idx) => (
                                            <div key={idx} className="p-3.5 rounded-xl bg-surface-2 border border-hairline space-y-2 text-xs">
                                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                                    <a
                                                        href={src.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="font-semibold text-accent hover:text-critical hover:underline flex items-center gap-1.5"
                                                    >
                                                        <span>🌐</span> {src.title || src.domain}
                                                    </a>
                                                    <div className="flex items-center gap-2 shrink-0">
                                                        <span className="text-[11px] px-2 py-0.5 rounded bg-surface text-ink-2 border border-hairline font-mono">
                                                            {src.domain}
                                                        </span>
                                                        <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded ${
                                                            src.found_in === "AI Overview"
                                                                ? "bg-purple-50 border border-purple-200 text-purple-700"
                                                                : "bg-blue-50 border border-blue-200 text-blue-700"
                                                        }`}>
                                                            {src.found_in}
                                                        </span>
                                                    </div>
                                                </div>
                                                {src.why && (
                                                    <div className="p-2.5 rounded-lg bg-surface border border-hairline text-ink-2">
                                                        <strong className="text-ink">Why: </strong>
                                                        {src.why}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Paragraphs to add */}
                            {aiPlan.paragraphs_to_add && aiPlan.paragraphs_to_add.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
                                            <span>✍️ Paragraphs to add</span>
                                            <span className="text-xs font-normal text-ink-3">({aiPlan.paragraphs_to_add.length})</span>
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-0.5">
                                            Ready-to-paste paragraphs, written only with facts from the page.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.paragraphs_to_add.map((p, idx) => (
                                            <div key={idx} className="p-3.5 rounded-xl bg-surface-2 border border-hairline space-y-2">
                                                <div className="flex items-center justify-between gap-2">
                                                    <div className="text-xs font-semibold text-ink">
                                                        🎯 {p.target_issue}
                                                    </div>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            navigator.clipboard.writeText(p.suggested_text);
                                                            alert("Paragraph copied to clipboard!");
                                                        }}
                                                        className="text-[11px] px-2 py-0.5 bg-surface hover:bg-surface-2 border border-hairline rounded text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                                    >
                                                        📋 Copy
                                                    </button>
                                                </div>
                                                <p className="text-xs text-ink leading-relaxed bg-surface p-2.5 rounded-lg border border-hairline">
                                                    {p.suggested_text}
                                                </p>
                                                <div className="text-[11px] text-ink-3 italic">
                                                    Placement: {p.placement}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Combined schema */}
                            {aiPlan.combined_schema && (
                                <div className="space-y-2 pb-6 border-b border-hairline">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="text-sm font-semibold text-ink">
                                                Combined schema
                                            </h4>
                                            <p className="text-xs text-ink-3 mt-0.5">
                                                For the developer: paste in the page &lt;head&gt;.
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleCopyCombinedSchema}
                                            className="text-xs px-2.5 py-1 bg-surface hover:bg-surface-2 border border-hairline rounded-lg text-ink-2 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                        >
                                            📋 Copy Schema
                                        </button>
                                    </div>
                                    <div className="p-4 bg-ink text-emerald-400 rounded-xl overflow-x-auto max-h-72 font-mono text-xs leading-relaxed">
                                        <pre>{JSON.stringify(aiPlan.combined_schema, null, 2)}</pre>
                                    </div>
                                </div>
                            )}

                            {/* Section: Rewrite Article with AI Plan */}
                            <div className="pt-2 space-y-6">
                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-2xl bg-surface-2 border border-hairline">
                                    <div>
                                        <h4 className="text-sm font-bold text-ink flex items-center gap-2">
                                            <span>✍️</span> Rewrite the article with this plan
                                        </h4>
                                        <p className="text-xs text-ink-3 mt-1 max-w-xl">
                                            Generate a complete draft for editor review applying the opening lead, heading hierarchy, FAQ block, and tables. Review side-by-side with before and after scores.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={handleRewriteArticle}
                                        disabled={isRewriting}
                                        className="btn-primary text-xs px-4 py-2.5 shrink-0 flex items-center gap-2 shadow-sm font-medium"
                                    >
                                        {isRewriting ? (
                                            <>
                                                <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full" />
                                                <span>Rewriting &amp; Auditing… (this can take a few minutes)</span>
                                            </>
                                        ) : (
                                            <>
                                                <span>🚀</span>
                                                <span>Rewrite the article with this plan</span>
                                            </>
                                        )}
                                    </button>
                                </div>

                                {rewriteError && (
                                    <div className="p-4 rounded-xl border border-critical/30 bg-critical-soft text-critical text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fade-in">
                                        <div className="flex items-center gap-2">
                                            <span className="text-base">⚠️</span>
                                            <span>{rewriteError}</span>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleRewriteArticle}
                                            disabled={isRewriting}
                                            className="btn-primary text-xs h-8 px-4 shrink-0 cursor-pointer font-medium"
                                        >
                                            {isRewriting ? "Retrying..." : "Try again"}
                                        </button>
                                    </div>
                                )}

                                {!rewriteError && rewriteDraft && (
                                    <div className="space-y-6 animate-fade-in">
                                        {/* Score comparison StatTiles */}
                                        {rewriteScore ? (() => {
                                            const totalBefore = Math.round(rewriteScore.total_score_before);
                                            const totalAfter = Math.round(rewriteScore.total_score_after);
                                            const totalDiff = totalAfter - totalBefore;
                                            return (
                                                <div className="space-y-4">
                                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                                        <StatTile
                                                            figure={`${totalBefore}`}
                                                            label="Original Content Score"
                                                            hint="On-page content before applying AI plan"
                                                            tone="neutral"
                                                        />
                                                        <StatTile
                                                            figure={`${totalAfter}`}
                                                            label="Rewritten Draft Score"
                                                            hint="On-page content with AI plan applied"
                                                            tone={totalDiff > 0 ? "good" : totalDiff < 0 ? "critical" : "neutral"}
                                                            change={{
                                                                value: `${totalDiff > 0 ? "+" : ""}${totalDiff} pts`,
                                                                direction: totalDiff > 0 ? "up" : totalDiff < 0 ? "down" : "flat",
                                                            }}
                                                        />
                                                    </div>

                                                    {/* Excluded dimensions notice */}
                                                    <p className="text-xs text-ink-3 italic">
                                                        Content-only comparison: technical, metadata, freshness and authority dimensions are not included.
                                                    </p>

                                                    {/* Dimension comparison table */}
                                                    {rewriteScore.dimensions && rewriteScore.dimensions.length > 0 && (
                                                        <div className="border border-hairline rounded-xl overflow-hidden bg-surface">
                                                            <div className="px-4 py-3 bg-surface-2 border-b border-hairline">
                                                                <h5 className="text-xs font-bold text-ink uppercase tracking-wider">
                                                                    Dimension Comparison
                                                                </h5>
                                                            </div>
                                                            <div className="overflow-x-auto">
                                                                <table className="w-full text-xs text-left">
                                                                    <thead className="bg-surface-2/60 text-ink-2 font-semibold border-b border-hairline">
                                                                        <tr>
                                                                            <th className="py-2.5 px-4">Dimension</th>
                                                                            <th className="py-2.5 px-4 text-center">Original</th>
                                                                            <th className="py-2.5 px-4 text-center">Draft</th>
                                                                            <th className="py-2.5 px-4 text-right">Change</th>
                                                                        </tr>
                                                                    </thead>
                                                                    <tbody className="divide-y divide-hairline">
                                                                        {rewriteScore.dimensions.map((dim, idx) => {
                                                                            const sBefore = Math.round(dim.score_before);
                                                                            const sAfter = Math.round(dim.score_after);
                                                                            const diff = sAfter - sBefore;
                                                                            return (
                                                                                <tr key={idx} className="hover:bg-surface-2/30 transition-colors">
                                                                                    <td className="py-2.5 px-4 font-medium text-ink">
                                                                                        {getDimensionDisplayName(dim.name)}
                                                                                    </td>
                                                                                    <td className="py-2.5 px-4 text-center font-mono text-ink-2">
                                                                                        {sBefore}/100
                                                                                    </td>
                                                                                    <td className="py-2.5 px-4 text-center font-mono text-ink font-semibold">
                                                                                        {sAfter}/100
                                                                                    </td>
                                                                                    <td className="py-2.5 px-4 text-right">
                                                                                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold font-mono ${
                                                                                            diff > 0
                                                                                                ? "bg-good-soft text-good"
                                                                                                : diff < 0
                                                                                                ? "bg-critical-soft text-critical"
                                                                                                : "bg-surface-2 text-ink-3"
                                                                                        }`}>
                                                                                            {diff > 0 ? "+" : ""}{diff}
                                                                                        </span>
                                                                                    </td>
                                                                                </tr>
                                                                            );
                                                                        })}
                                                                    </tbody>
                                                                </table>
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })() : rewriteScoreError ? (
                                            <div className="p-4 rounded-xl border border-warn/30 bg-warn-soft/60 text-xs text-ink space-y-1">
                                                <div className="flex items-center gap-2 font-bold text-warn">
                                                    <span>⚠️</span>
                                                    <span>Score comparison failed: {rewriteScoreError}</span>
                                                </div>
                                                <p className="text-ink-2">
                                                    The draft was generated successfully, but automated re-scoring could not be completed. You can still review and export the draft below.
                                                </p>
                                            </div>
                                        ) : null}

                                        {/* Warnings callout box */}
                                        {rewriteDraft.warnings && rewriteDraft.warnings.length > 0 && (
                                            <div className="p-4 rounded-xl border border-warn/30 bg-warn-soft/60 space-y-2">
                                                <div className="flex items-center gap-2 text-xs font-bold text-warn">
                                                    <span>⚠️</span>
                                                    <span>Editorial Warnings ({rewriteDraft.warnings.length})</span>
                                                </div>
                                                <ul className="text-xs text-ink leading-relaxed space-y-1 list-disc pl-5">
                                                    {rewriteDraft.warnings.map((warn, wIdx) => (
                                                        <li key={wIdx}>{warn}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {/* Download error display */}
                                        {draftDownloadError && (
                                            <div className="p-3.5 rounded-xl border border-critical/30 bg-critical-soft text-critical text-xs flex items-center justify-between gap-2 animate-fade-in">
                                                <div className="flex items-center gap-2">
                                                    <span>⚠️</span>
                                                    <span>Failed to download Word draft: {draftDownloadError}</span>
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() => setDraftDownloadError(null)}
                                                    className="text-critical hover:text-critical/80 text-xs font-bold px-1.5 py-0.5 rounded cursor-pointer"
                                                >
                                                    ✕
                                                </button>
                                            </div>
                                        )}

                                        {/* Action buttons & Word counts bar */}
                                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 bg-surface-2 rounded-xl border border-hairline">
                                            <div className="flex items-center gap-3 text-xs text-ink-3 font-medium">
                                                <span>Original: {rewriteDraft.word_count_original} words</span>
                                                <span>·</span>
                                                <span>Draft: {rewriteDraft.word_count_draft} words</span>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() => setShowOriginalText(!showOriginalText)}
                                                    className="btn-default text-xs h-8 px-3 flex items-center gap-1.5 cursor-pointer font-medium"
                                                >
                                                    <span>{showOriginalText ? "👁️ Hide Original" : "👁️ Show Original"}</span>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={handleCopyRewriteMarkdown}
                                                    disabled={!hasDraftContent}
                                                    className={`btn-default text-xs h-8 px-3 flex items-center gap-1.5 font-medium ${!hasDraftContent ? "opacity-50 cursor-not-allowed pointer-events-none" : "cursor-pointer"}`}
                                                >
                                                    <span>{copiedMarkdown ? "✓ Copied" : "📋 Copy as Markdown"}</span>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={handleCopyRewriteHtml}
                                                    disabled={!hasDraftContent}
                                                    className={`btn-default text-xs h-8 px-3 flex items-center gap-1.5 font-medium ${!hasDraftContent ? "opacity-50 cursor-not-allowed pointer-events-none" : "cursor-pointer"}`}
                                                >
                                                    <span>{copiedHtml ? "✓ Copied" : "🌐 Copy as HTML"}</span>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={handleDownloadRewriteDocx}
                                                    disabled={!hasDraftContent || isDraftDownloading}
                                                    className={`btn-primary text-xs h-8 px-3.5 flex items-center gap-1.5 font-medium ${(!hasDraftContent || isDraftDownloading) ? "opacity-50 cursor-not-allowed pointer-events-none" : "cursor-pointer"}`}
                                                >
                                                    {isDraftDownloading ? (
                                                        <>
                                                            <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                                                            <span>Downloading...</span>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <span>📥</span>
                                                            <span>Download draft (.docx)</span>
                                                        </>
                                                    )}
                                                </button>
                                            </div>
                                        </div>

                                        {/* Side by side comparison or Original toggle */}
                                        {showOriginalText && (
                                            <div className="p-5 rounded-2xl bg-surface-2 border border-hairline space-y-2">
                                                <h5 className="text-xs font-bold text-ink uppercase tracking-wider">
                                                    Original Scraped Content
                                                </h5>
                                                <div className="text-xs text-ink-2 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto p-4 bg-surface rounded-xl border border-hairline font-serif">
                                                    {results.ai_context?.main_text || originalText || "No original text available."}
                                                </div>
                                            </div>
                                        )}

                                        {/* Rendered Draft Content */}
                                        <div className="p-6 sm:p-8 rounded-2xl bg-surface border border-hairline space-y-5 shadow-sm">
                                            <div className="flex items-center justify-between pb-3 border-b border-hairline">
                                                <h4 className="text-base font-bold text-ink">
                                                    Rewritten Draft
                                                </h4>
                                                <span className="text-xs text-ink-3">
                                                    Editor review recommended before publishing
                                                </span>
                                            </div>

                                            <div className="prose prose-sm dark:prose-invert max-w-none space-y-4">
                                                {(() => {
                                                    const renderDraftInline = (text: string) => {
                                                        const tokenRegex = /(\[EDITOR:[^\]]+\]|!\[[^\]]*\]\(https?:\/\/[^)\s]+\)|\[[^\]]*\]\(https?:\/\/[^)\s]+\))/g;
                                                        const parts = text.split(tokenRegex);
                                                        return parts.map((part, idx) => {
                                                            if (!part) return null;
                                                            if (part.startsWith('[EDITOR:') && part.endsWith(']')) {
                                                                return (
                                                                    <span
                                                                        key={idx}
                                                                        className="inline-block bg-amber-100 dark:bg-amber-950/60 border border-amber-300 dark:border-amber-700/60 text-amber-900 dark:text-amber-200 font-bold px-1.5 py-0.5 rounded text-xs mx-0.5 shadow-2xs"
                                                                    >
                                                                        {part}
                                                                    </span>
                                                                );
                                                            }
                                                            const imgMatch = part.match(/^!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)$/);
                                                            if (imgMatch) {
                                                                const alt = imgMatch[1];
                                                                const src = imgMatch[2];
                                                                if (/^https?:\/\//i.test(src)) {
                                                                    return (
                                                                        <img
                                                                            key={idx}
                                                                            src={src}
                                                                            alt={alt}
                                                                            className="inline-block max-h-48 rounded border border-hairline my-1"
                                                                            loading="lazy"
                                                                        />
                                                                    );
                                                                }
                                                            }
                                                            const linkMatch = part.match(/^\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)$/);
                                                            if (linkMatch) {
                                                                const anchorText = linkMatch[1] || linkMatch[2];
                                                                const href = linkMatch[2];
                                                                if (/^https?:\/\//i.test(href)) {
                                                                    return (
                                                                        <a
                                                                            key={idx}
                                                                            href={href}
                                                                            target="_blank"
                                                                            rel="noopener noreferrer"
                                                                            className="underline text-accent hover:text-critical font-medium transition-colors"
                                                                        >
                                                                            {anchorText}
                                                                        </a>
                                                                    );
                                                                }
                                                            }
                                                            // Format bold (**...**) and italic (*...*) safely without innerHTML
                                                            const styleRegex = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;
                                                            const subparts = part.split(styleRegex);
                                                            return (
                                                                <React.Fragment key={idx}>
                                                                    {subparts.map((sub, sIdx) => {
                                                                        if (!sub) return null;
                                                                        if (sub.startsWith('**') && sub.endsWith('**') && sub.length >= 4) {
                                                                            return <strong key={sIdx}>{sub.slice(2, -2)}</strong>;
                                                                        }
                                                                        if (sub.startsWith('*') && sub.endsWith('*') && sub.length >= 2) {
                                                                            return <em key={sIdx}>{sub.slice(1, -1)}</em>;
                                                                        }
                                                                        return <span key={sIdx}>{sub}</span>;
                                                                    })}
                                                                </React.Fragment>
                                                            );
                                                        });
                                                    };

                                                    return rewriteDraft.draft_markdown.split('\n\n').map((block, bIdx) => {
                                                        const trimmed = block.trim();
                                                        if (!trimmed) return null;

                                                        // Standalone Markdown image block
                                                        const imgBlockMatch = trimmed.match(/^!\[([^\]]*)\]\((https?:\/\/[^)\s]+)(?:\s+"[^"]*")?\)$/);
                                                        if (imgBlockMatch) {
                                                            const alt = imgBlockMatch[1];
                                                            const src = imgBlockMatch[2];
                                                            if (/^https?:\/\//i.test(src)) {
                                                                return (
                                                                    <figure key={bIdx} className="my-4">
                                                                        <img
                                                                            src={src}
                                                                            alt={alt}
                                                                            className="max-w-full h-auto rounded-xl border border-hairline shadow-sm"
                                                                            loading="lazy"
                                                                        />
                                                                        {alt && (
                                                                            <figcaption className="text-xs text-ink-3 italic mt-1.5 text-center">
                                                                                {alt}
                                                                            </figcaption>
                                                                        )}
                                                                    </figure>
                                                                );
                                                            }
                                                        }

                                                        // Markdown table block
                                                        if (trimmed.startsWith('|') && trimmed.includes('\n|')) {
                                                            const lines = trimmed.split('\n').filter(l => l.trim().startsWith('|'));
                                                            const headers = lines[0].slice(1, -1).split('|').map(c => c.trim());
                                                            const rows = lines.slice(2).map(l => l.slice(1, -1).split('|').map(c => c.trim()));
                                                            return (
                                                                <div key={bIdx} className="overflow-x-auto my-4 border border-hairline rounded-xl">
                                                                    <table className="w-full text-xs text-left">
                                                                        <thead className="bg-surface-2 text-ink font-semibold border-b border-hairline">
                                                                            <tr>
                                                                                {headers.map((h, hIdx) => (
                                                                                    <th key={hIdx} className="py-2 px-3 border-r border-hairline last:border-r-0">
                                                                                        {renderDraftInline(h)}
                                                                                    </th>
                                                                                ))}
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody className="divide-y divide-hairline bg-surface">
                                                                            {rows.map((r, rIdx) => (
                                                                                <tr key={rIdx}>
                                                                                    {r.map((cell, cIdx) => (
                                                                                        <td key={cIdx} className="py-2 px-3 border-r border-hairline last:border-r-0 text-ink-2">
                                                                                            {renderDraftInline(cell)}
                                                                                        </td>
                                                                                    ))}
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                </div>
                                                            );
                                                        }

                                                        // Heading 1
                                                        if (trimmed.startsWith('# ')) {
                                                            return (
                                                                <h1 key={bIdx} className="text-xl sm:text-2xl font-extrabold text-ink tracking-tight pt-2">
                                                                    {renderDraftInline(trimmed.slice(2))}
                                                                </h1>
                                                            );
                                                        }

                                                        // Heading 2
                                                        if (trimmed.startsWith('## ')) {
                                                            return (
                                                                <h2 key={bIdx} className="text-lg font-bold text-ink tracking-tight pt-3 border-t border-hairline/60">
                                                                    {renderDraftInline(trimmed.slice(3))}
                                                                </h2>
                                                            );
                                                        }

                                                        // Heading 3
                                                        if (trimmed.startsWith('### ')) {
                                                            const hLines = trimmed.split('\n');
                                                            const headingText = hLines[0].slice(4);
                                                            const restText = hLines.slice(1).join('\n').trim();
                                                            return (
                                                                <div key={bIdx} className="space-y-1 pt-1">
                                                                    <h3 className="text-sm font-bold text-ink">
                                                                        {renderDraftInline(headingText)}
                                                                    </h3>
                                                                    {restText && (
                                                                        <p className="text-xs sm:text-sm text-ink leading-relaxed">
                                                                            {renderDraftInline(restText)}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            );
                                                        }

                                                        // Bullet lists
                                                        if (trimmed.startsWith('- ')) {
                                                            const items = trimmed.split('\n').filter(l => l.trim().startsWith('- '));
                                                            return (
                                                                <ul key={bIdx} className="list-disc pl-5 space-y-1 text-xs text-ink-2 leading-relaxed">
                                                                    {items.map((item, iIdx) => (
                                                                        <li key={iIdx}>
                                                                            {renderDraftInline(item.slice(2))}
                                                                        </li>
                                                                    ))}
                                                                </ul>
                                                            );
                                                        }

                                                        // Standard paragraph with [EDITOR: ...], images and links
                                                        return (
                                                            <p key={bIdx} className="text-xs sm:text-sm text-ink leading-relaxed">
                                                                {renderDraftInline(trimmed)}
                                                            </p>
                                                        );
                                                    });
                                                })()}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
