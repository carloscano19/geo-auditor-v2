"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
    type AuditResponse,
    type AIFixesResponse,
    type AIPlanResponse,
    type AhrefsOffpageResponse,
    getDimensionDisplayName,
    apiClient,
} from "@/lib/api";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";

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

export default function AuditResults({ results, hideAiFixes = false }: AuditResultsProps) {
    const [activeTab, setActiveTab] = useState<"overview" | "dimensions" | "ai_plan">("overview");
    const [openDimensions, setOpenDimensions] = useState<Record<string, boolean>>({});

    const [isAiLoading, setIsAiLoading] = useState(false);
    const [isPlanLoading, setIsPlanLoading] = useState(false);
    const [isBriefDownloading, setIsBriefDownloading] = useState(false);
    const [customQuery, setCustomQuery] = useState("");
    const [isEditingQuery, setIsEditingQuery] = useState(false);
    const [aiFixes, setAiFixes] = useState<AIFixesResponse | null>(null);
    const [aiPlan, setAiPlan] = useState<AIPlanResponse | null>(null);
    const [aiFixesError, setAiFixesError] = useState<string | null>(null);
    const [aiPlanError, setAiPlanError] = useState<string | null>(null);
    const [copiedSources, setCopiedSources] = useState(false);

    // Ahrefs Off-page state
    const [ahrefsEnabled, setAhrefsEnabled] = useState(false);
    const [isAhrefsLoading, setIsAhrefsLoading] = useState(false);
    const [ahrefsData, setAhrefsData] = useState<AhrefsOffpageResponse | null>(null);
    const [ahrefsError, setAhrefsError] = useState<string | null>(null);

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

    const handleGenerateAIFixes = async () => {
        if (!results.ai_context) return;
        setIsAiLoading(true);
        setAiFixesError(null);
        try {
            const data = await apiClient.generateAIFixes(results.ai_context);
            setAiFixes(data);
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to generate AI fixes";
            setAiFixesError(errorMsg);
        } finally {
            setIsAiLoading(false);
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

    const handleGenerateAllAI = async () => {
        if (!results.ai_context) return;
        setIsAiLoading(true);
        setIsPlanLoading(true);
        setAiFixesError(null);
        setAiPlanError(null);

        const fixesPromise = apiClient.generateAIFixes(results.ai_context);
        const planPromise = apiClient.generateAIPlan(results.ai_context);

        const [fixesResult, planResult] = await Promise.allSettled([fixesPromise, planPromise]);

        if (fixesResult.status === "fulfilled") {
            setAiFixes(fixesResult.value);
        } else {
            const msg = fixesResult.reason instanceof Error ? fixesResult.reason.message : "Failed to generate quick fixes";
            setAiFixesError(msg);
        }

        if (planResult.status === "fulfilled") {
            setAiPlan(planResult.value);
            if (planResult.value.serp_query) {
                setCustomQuery(planResult.value.serp_query);
            }
            setIsEditingQuery(false);
        } else {
            const msg = planResult.reason instanceof Error ? planResult.reason.message : "Failed to generate improvement plan";
            setAiPlanError(msg);
        }

        setIsAiLoading(false);
        setIsPlanLoading(false);
    };

    const handleDownloadEditorBrief = async () => {
        setIsBriefDownloading(true);
        try {
            await apiClient.downloadEditorBrief({
                audit_result: results,
                ai_fixes: aiFixes,
                ai_plan: aiPlan,
                ahrefs_offpage: ahrefsData,
            });
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to download editor brief";
            alert(`Error downloading brief: ${errorMsg}`);
        } finally {
            setIsBriefDownloading(false);
        }
    };

    const handleCopyJsonLd = () => {
        if (!aiFixes?.json_ld) return;
        navigator.clipboard.writeText(JSON.stringify(aiFixes.json_ld, null, 2));
        alert("Schema.org JSON-LD copied to clipboard!");
    };

    const handleCopyLeadParagraph = () => {
        if (!aiFixes?.lead_paragraph?.suggested) return;
        navigator.clipboard.writeText(aiFixes.lead_paragraph.suggested);
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
            lines.push(`*Use these headings to organise the page. 'New' means the section has to be written.*\n`);
            aiPlan.suggested_h2_structure.forEach((h, i) => {
                const statusBadge = h.status === "existing" ? "[Exists — add the heading]" : "[New — write this section]";
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
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 bg-white border border-slate-200 rounded-2xl shadow-2xs no-print">
                <div className="flex flex-wrap items-center gap-2">
                    <button
                        type="button"
                        onClick={handleCopySummary}
                        className="text-xs px-3.5 py-2 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-slate-700 shadow-2xs transition-all flex items-center gap-2 cursor-pointer font-medium"
                    >
                        <span>📋</span>
                        <span>Copy Summary for Slack</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => window.print()}
                        className="text-xs px-3.5 py-2 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-slate-700 shadow-2xs transition-all flex items-center gap-2 cursor-pointer font-medium"
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
                        className="text-xs px-3.5 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded-xl shadow-xs transition-all flex items-center gap-2 cursor-pointer font-medium"
                    >
                        {isBriefDownloading ? (
                            <>
                                <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full" />
                                <span>Generating .docx...</span>
                            </>
                        ) : (
                            <>
                                <span>📄</span>
                                <span>Download editor brief (.docx)</span>
                            </>
                        )}
                    </button>
                    {((aiFixes || aiPlan) || ahrefsData) && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                            {(aiFixes || aiPlan) && (
                                <span className="text-[11px] px-2 py-0.5 rounded-md bg-slate-100 border border-slate-200 text-slate-600 font-medium">
                                    Includes AI recommendations
                                </span>
                            )}
                            {ahrefsData && (
                                <span className="text-[11px] px-2 py-0.5 rounded-md bg-slate-100 border border-slate-200 text-slate-600 font-medium">
                                    Includes Ahrefs data
                                </span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Tab Navigation Switcher */}
            <div className="flex items-center gap-2 border-b border-slate-200 pb-3 no-print">
                <button
                    type="button"
                    onClick={() => setActiveTab("overview")}
                    className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 ${
                        activeTab === "overview"
                            ? "bg-red-50 text-red-700 border border-red-200 shadow-2xs"
                            : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent"
                    }`}
                >
                    <span>📊</span>
                    <span>Overview</span>
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab("dimensions")}
                    className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 ${
                        activeTab === "dimensions"
                            ? "bg-red-50 text-red-700 border border-red-200 shadow-2xs"
                            : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent"
                    }`}
                >
                    <span>📑</span>
                    <span>Dimensions</span>
                    <span className="text-[10px] px-1.5 py-0.2 rounded-full font-mono font-bold bg-slate-200/80 text-slate-700">
                        {results.detector_results.length}
                    </span>
                </button>
                {!hideAiFixes && results.ai_context && (
                    <button
                        type="button"
                        onClick={() => setActiveTab("ai_plan")}
                        className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer flex items-center gap-2 ${
                            activeTab === "ai_plan"
                                ? "bg-red-50 text-red-700 border border-red-200 shadow-2xs"
                                : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent"
                        }`}
                    >
                        <span>✨</span>
                        <span>AI Plan</span>
                        {(aiFixes || aiPlan) && (
                            <span className="w-2 h-2 rounded-full bg-red-600 animate-pulse" />
                        )}
                    </button>
                )}
            </div>

            {/* TAB 1: OVERVIEW */}
            <div className={`space-y-6 ${activeTab === "overview" ? "block" : "hidden print:block"}`}>
                {/* Score & Meta Card */}
                <div className="glass-card p-6 sm:p-8">
                    <div className="flex flex-col lg:flex-row items-center gap-8">
                        {/* Score Circle */}
                        <div className="flex flex-col items-center shrink-0">
                            <ScoreDisplay
                                score={results.total_score}
                                label="Citation Score"
                                sublabel="Measures on-page readiness for AI citation. Off-page factors like organic rankings and brand authority are not included."
                            />
                            {results.score_capped && (
                                <div className="mt-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs font-medium text-center max-w-xs">
                                    ⚠️ Score capped at 30: {results.cap_reason}
                                </div>
                            )}
                        </div>

                        {/* Metadata & Actions */}
                        <div className="flex-1 text-center lg:text-left min-w-0">
                            <div className="flex flex-col justify-between items-start gap-3">
                                <div className="w-full">
                                    <div className="flex items-center gap-2 justify-center lg:justify-start flex-wrap mb-1">
                                        <h2 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
                                            Audit Overview
                                        </h2>
                                        <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-slate-100 text-slate-600 border border-slate-200">
                                            {results.scoring_version}
                                        </span>
                                    </div>
                                    <p
                                        title={results.url || results.ai_context?.title || "Direct Text Submission"}
                                        className="text-xs sm:text-sm text-slate-500 mb-2 truncate max-w-2xl"
                                    >
                                        {results.url || results.ai_context?.title || "Direct Text Submission"}
                                    </p>
                                </div>
                            </div>

                            {/* Details meta footer */}
                            <div className="flex flex-wrap gap-4 justify-center lg:justify-start text-xs text-slate-500 mt-6 pt-4 border-t border-slate-100 font-medium">
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
                <div className="glass-card p-6">
                    <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-red-100 text-red-700 flex items-center justify-center text-sm font-bold shadow-2xs">
                                ⚡
                            </div>
                            <div>
                                <h3 className="text-base font-bold text-slate-900 tracking-tight">
                                    Top 5 Actions
                                </h3>
                                <p className="text-xs text-slate-500">
                                    Highest-impact non-technical fixes to improve citability
                                </p>
                            </div>
                        </div>
                    </div>

                    {topActions.length === 0 ? (
                        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-800 text-xs flex items-center gap-2">
                            <span>✓</span>
                            <span>All non-technical content scored 70 or higher. No critical editorial weaknesses found!</span>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {topActions.map((action, idx) => (
                                <div
                                    key={idx}
                                    className="p-4 bg-slate-50/70 border border-slate-200 rounded-xl flex flex-col sm:flex-row sm:items-start justify-between gap-3 transition-all hover:bg-slate-50"
                                >
                                    <div className="space-y-1.5 flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="w-5 h-5 rounded-full bg-slate-900 text-white text-xs font-bold flex items-center justify-center shrink-0">
                                                {idx + 1}
                                            </span>
                                            <span className="text-sm font-bold text-slate-900">
                                                {action.friendlyName}
                                            </span>
                                            <span className="text-[11px] font-bold font-mono px-2 py-0.5 rounded bg-red-50 text-red-700 border border-red-200">
                                                Score: {Math.round(action.rawScore)}/100
                                            </span>
                                        </div>
                                        <p className="text-xs text-slate-700 pl-7 leading-relaxed">
                                            {action.recommendation}
                                        </p>
                                    </div>
                                    <div className="sm:text-right shrink-0 pl-7 sm:pl-0">
                                        <span className="text-slate-400 font-mono text-xs">
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
                    <div className="glass-card p-6">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                            <div className="flex items-center gap-2.5">
                                <div className="w-8 h-8 rounded-lg bg-orange-100 text-orange-700 flex items-center justify-center text-sm font-bold shadow-2xs">
                                    🔗
                                </div>
                                <div>
                                    <h3 className="text-base font-bold text-slate-900 tracking-tight">
                                        Off-page Signals (Ahrefs)
                                    </h3>
                                    <p className="text-xs text-slate-500">
                                        External backlink, authority, and ranking indicators
                                    </p>
                                </div>
                            </div>

                            {ahrefsEnabled && (
                                <button
                                    type="button"
                                    onClick={handleCheckAhrefs}
                                    disabled={isAhrefsLoading}
                                    className="text-xs px-3.5 py-2 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-slate-700 shadow-2xs transition-all flex items-center gap-2 cursor-pointer font-medium no-print"
                                >
                                    {isAhrefsLoading ? (
                                        <>
                                            <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-slate-700 border-t-transparent rounded-full" />
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
                            <p className="text-xs text-slate-500">
                                Ahrefs integration is disabled. Set <code className="font-mono text-[11px] bg-slate-100 px-1 py-0.5 rounded text-slate-700">GEO_AUDITOR_AHREFS_API_KEY</code> to enable live authority and backlink metrics.
                            </p>
                        )}

                        {ahrefsError && (
                            <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 mt-2 flex items-center justify-between gap-2">
                                <span>⚠️ {ahrefsError}</span>
                                <button
                                    type="button"
                                    onClick={handleCheckAhrefs}
                                    disabled={isAhrefsLoading}
                                    className="underline text-red-800 font-semibold cursor-pointer"
                                >
                                    Retry
                                </button>
                            </div>
                        )}

                        {ahrefsData && (
                            <div className="space-y-4 mt-3">
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Domain Rating</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.domain_rating != null ? ahrefsData.domain_rating : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">URL Rating</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.url_rating != null ? ahrefsData.url_rating : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Referring Domains</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.referring_domains != null ? ahrefsData.referring_domains.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Backlinks</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.backlinks != null ? ahrefsData.backlinks.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Organic Keywords</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.organic_keywords != null ? ahrefsData.organic_keywords.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Top 3 Keywords</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.top3_keywords != null ? ahrefsData.top3_keywords.toLocaleString() : "—"}
                                        </p>
                                    </div>
                                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 sm:col-span-2">
                                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Organic Traffic/Month</p>
                                        <p className="text-xl font-bold font-mono text-slate-900 mt-0.5">
                                            {ahrefsData.organic_traffic != null ? Math.round(ahrefsData.organic_traffic).toLocaleString() : "—"}
                                        </p>
                                    </div>
                                </div>

                                {/* Who links to this page */}
                                <div className="pt-2">
                                    <p className="text-xs font-bold text-slate-700 mb-2 uppercase tracking-wider">
                                        Who links to this page
                                    </p>
                                    {ahrefsData.linking_pages === null ? (
                                        <p className="text-xs text-slate-500 italic py-1">Link list unavailable.</p>
                                    ) : ahrefsData.linking_pages.length === 0 ? (
                                        <p className="text-xs text-slate-500 italic py-1">No live links found.</p>
                                    ) : (
                                        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
                                            <table className="w-full text-left text-xs">
                                                <thead className="bg-slate-50 border-b border-slate-200 text-slate-700 font-semibold">
                                                    <tr>
                                                        <th className="px-3 py-2.5">Domain</th>
                                                        <th className="px-3 py-2.5">DR</th>
                                                        <th className="px-3 py-2.5">Linking page</th>
                                                        <th className="px-3 py-2.5">Anchor</th>
                                                        <th className="px-3 py-2.5">Type</th>
                                                        <th className="px-3 py-2.5">First seen</th>
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-slate-100 text-slate-700">
                                                    {ahrefsData.linking_pages.map((link, idx) => (
                                                        <tr key={idx} className={link.spam ? "bg-red-50/50" : "hover:bg-slate-50/50"}>
                                                            <td className="px-3 py-2 font-medium text-slate-900 whitespace-nowrap">
                                                                <div className="flex items-center gap-1.5">
                                                                    <span>{link.domain}</span>
                                                                    {link.spam && (
                                                                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-700 border border-red-200">
                                                                            Spam
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            </td>
                                                            <td className="px-3 py-2 font-mono text-slate-800">
                                                                {link.domain_rating != null ? link.domain_rating : "—"}
                                                            </td>
                                                            <td className="px-3 py-2 max-w-[200px] truncate">
                                                                <a
                                                                    href={link.url_from}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    className="text-red-600 hover:underline truncate block"
                                                                    title={link.url_from}
                                                                >
                                                                    {link.url_from}
                                                                </a>
                                                            </td>
                                                            <td className="px-3 py-2 max-w-[160px] truncate text-slate-600" title={link.anchor}>
                                                                {link.anchor || <span className="text-slate-400 italic">No anchor</span>}
                                                            </td>
                                                            <td className="px-3 py-2 whitespace-nowrap">
                                                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                                                                    link.dofollow
                                                                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                                                        : "bg-slate-100 text-slate-600 border border-slate-200"
                                                                }`}>
                                                                    {link.dofollow ? "Dofollow" : "Nofollow"}
                                                                </span>
                                                            </td>
                                                            <td className="px-3 py-2 whitespace-nowrap text-slate-500 font-mono text-[11px]">
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
                                        <p className="text-xs font-bold text-slate-700 mb-2 uppercase tracking-wider">
                                            Off-page Recommendations:
                                        </p>
                                        <ul className="space-y-1.5 text-xs text-slate-700">
                                            {ahrefsData.recommendations.map((rec, idx) => (
                                                <li key={idx} className="flex items-start gap-2 bg-slate-50 p-2.5 rounded-lg border border-slate-200/80 leading-relaxed">
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
                <div className="glass-card p-6">
                    <div className="flex items-center gap-2.5 mb-2">
                        <div className="w-8 h-8 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center text-sm font-bold shadow-2xs">
                            ℹ️
                        </div>
                        <h4 className="text-base font-bold text-slate-900 tracking-tight">
                            Not measured by this tool
                        </h4>
                    </div>
                    {ahrefsData && (
                        <p className="text-xs text-emerald-700 font-medium mb-3 flex items-center gap-1.5">
                            <span>✓</span> Partially covered above with Ahrefs data.
                        </p>
                    )}
                    <p className="text-xs text-slate-500 mb-4 leading-relaxed">
                        The Citation Score measures on-page architectural and content readiness. Leading AI engines (ChatGPT, Perplexity, Gemini) also consider external signals:
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                            <span className="text-lg">📊</span>
                            <div>
                                <p className="font-semibold text-slate-900 text-xs">Organic ranking position</p>
                                <p className="text-[11px] text-slate-500">Domain authority & traditional search ranking</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                            <span className="text-lg">🏷️</span>
                            <div>
                                <p className="font-semibold text-slate-900 text-xs">Brand mentions on third-party sites</p>
                                <p className="text-[11px] text-slate-500">Unlinked co-citations and web consensus</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                            <span className="text-lg">📱</span>
                            <div>
                                <p className="font-semibold text-slate-900 text-xs">Presence on YouTube / Reddit / social</p>
                                <p className="text-[11px] text-slate-500">Community discussion and multimedia footprints</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
                            <span className="text-lg">🏛️</span>
                            <div>
                                <p className="font-semibold text-slate-900 text-xs">Publisher reputation</p>
                                <p className="text-[11px] text-slate-500">Historical accuracy & verified entity graph status</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* TAB 2: DIMENSIONS */}
            <div className={`space-y-4 ${activeTab === "dimensions" ? "block" : "hidden print:block"}`}>
                <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
                    <div>
                        <h3 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
                            Citability Dimensions ({results.detector_results.length})
                        </h3>
                        <p className="text-xs text-slate-500">
                            Click any dimension to expand submetrics, explanations, and evidence
                        </p>
                    </div>

                    <div className="flex items-center gap-2 no-print">
                        <button
                            type="button"
                            onClick={handleExpandAllDimensions}
                            className="text-xs px-3 py-1.5 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer"
                        >
                            Expand All
                        </button>
                        <button
                            type="button"
                            onClick={handleCollapseAllDimensions}
                            className="text-xs px-3 py-1.5 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer"
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
                    <div className="glass-card p-6 border-slate-200">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                            <div>
                                <div className="flex items-center gap-2">
                                    <span className="text-xl">✨</span>
                                    <h3 className="text-lg font-bold text-slate-900 tracking-tight">
                                        AI Suggested Fixes &amp; Content Plan
                                    </h3>
                                </div>
                                <p className="text-xs text-slate-500 mt-1 max-w-xl">
                                    Generated with the Chiliz AI model and live Google data. Figures and links are checked against the page and Google results. Review before publishing.
                                </p>
                            </div>

                            <div className="flex flex-wrap gap-2.5 no-print">
                                <button
                                    type="button"
                                    onClick={handleGenerateAllAI}
                                    disabled={isAiLoading || isPlanLoading}
                                    className="btn-primary text-xs px-4 py-2 flex items-center gap-2"
                                >
                                    {(isAiLoading || isPlanLoading) ? (
                                        <>
                                            <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full" />
                                            <span>Generating with AI… this can take up to a minute.</span>
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

                    {/* Empty State when neither generated yet */}
                    {!aiFixes && !aiPlan && !isAiLoading && !isPlanLoading && !aiFixesError && !aiPlanError && (
                        <div className="glass-card p-10 text-center space-y-4">
                            <div className="w-12 h-12 mx-auto rounded-2xl bg-red-50 text-red-600 flex items-center justify-center text-2xl font-bold shadow-2xs">
                                ✨
                            </div>
                            <div className="max-w-md mx-auto space-y-2">
                                <h4 className="text-base font-bold text-slate-900">
                                    Generate AI Recommendations
                                </h4>
                                <p className="text-xs text-slate-500 leading-relaxed">
                                    Generate actionable AI recommendations including quick fixes (an optimized opening paragraph and Schema.org JSON-LD) and a full content improvement plan (Google PAA questions, heading hierarchy, comparison table, content opportunities, and authoritative sources to cite).
                                </p>
                                <div className="pt-2">
                                    <button
                                        type="button"
                                        onClick={handleGenerateAllAI}
                                        className="btn-primary text-xs px-4 py-2 inline-flex items-center gap-2"
                                    >
                                        <span>✨</span>
                                        <span>Generate AI recommendations</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Quick Fixes Error Notice with Retry */}
                    {aiFixesError && (
                        <div className="glass-card p-4 border-amber-200 bg-amber-50/50">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                <div className="flex items-center gap-2 text-xs text-amber-800 font-medium">
                                    <span>⚠️</span>
                                    <span>Quick fixes could not be generated: {aiFixesError}</span>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleGenerateAIFixes}
                                    disabled={isAiLoading}
                                    className="text-xs px-3.5 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium rounded-xl shadow-2xs transition-all cursor-pointer whitespace-nowrap self-start sm:self-auto"
                                >
                                    {isAiLoading ? "Retrying..." : "Retry Quick fixes"}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* 1. Quick Fixes Output */}
                    {aiFixes && (
                        <div className="glass-card p-6 space-y-6">
                            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                                <h4 className="text-base font-bold text-slate-900 flex items-center gap-2">
                                    <span>⚡</span> Quick Fixes (Lead Paragraph & Schema.org)
                                </h4>
                                <span className="text-[11px] font-mono text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md font-semibold">
                                    Ready
                                </span>
                            </div>

                            {/* Lead Paragraph Fix */}
                            {aiFixes.lead_paragraph && (
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between">
                                        <h5 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                                            1. Lead Paragraph (First 60 Words / Rule of 60)
                                        </h5>
                                        <button
                                            type="button"
                                            onClick={handleCopyLeadParagraph}
                                            className="text-xs text-slate-600 hover:text-slate-900 underline font-medium cursor-pointer"
                                        >
                                            Copy Suggested Text
                                        </button>
                                    </div>

                                    {aiFixes.lead_paragraph.rationale && (
                                        <p className="text-xs text-slate-500 italic">
                                            {aiFixes.lead_paragraph.rationale}
                                        </p>
                                    )}

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5">
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                                                Current Text
                                            </span>
                                            <p className="text-xs text-slate-700 leading-relaxed font-mono">
                                                {aiFixes.lead_paragraph.original || "(Empty or undetected lead)"}
                                            </p>
                                        </div>
                                        <div className="p-4 bg-emerald-50/50 border border-emerald-200/80 rounded-xl space-y-1.5">
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                                                Suggested Optimized Opening
                                            </span>
                                            <p className="text-xs text-slate-800 leading-relaxed font-mono font-medium">
                                                {aiFixes.lead_paragraph.suggested}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Schema.org Fix */}
                            {aiFixes.json_ld && (
                                <div className="space-y-3 pt-4 border-t border-slate-100">
                                    <div className="flex items-center justify-between">
                                        <h5 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                                            2. Suggested Schema.org (JSON-LD)
                                        </h5>
                                        <button
                                            type="button"
                                            onClick={handleCopyJsonLd}
                                            className="text-xs text-slate-600 hover:text-slate-900 underline font-medium cursor-pointer"
                                        >
                                            Copy JSON-LD
                                        </button>
                                    </div>

                                    {aiFixes.warnings && aiFixes.warnings.length > 0 && (
                                        <ul className="space-y-1 text-xs text-slate-600">
                                            {aiFixes.warnings.map((rec, idx) => (
                                                <li key={idx} className="flex items-start gap-1.5">
                                                    <span className="text-amber-600 font-bold">•</span>
                                                    <span>{rec}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    )}

                                    <div className="p-4 bg-slate-900 text-slate-200 rounded-xl overflow-x-auto max-h-72 font-mono text-xs leading-relaxed">
                                        <pre>{JSON.stringify(aiFixes.json_ld, null, 2)}</pre>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Full Plan Error Notice with Retry */}
                    {aiPlanError && (
                        <div className="glass-card p-4 border-amber-200 bg-amber-50/50">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                <div className="flex items-center gap-2 text-xs text-amber-800 font-medium">
                                    <span>⚠️</span>
                                    <span>Full improvement plan could not be generated: {aiPlanError}</span>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => handleGenerateAIPlan()}
                                    disabled={isPlanLoading}
                                    className="text-xs px-3.5 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium rounded-xl shadow-2xs transition-all cursor-pointer whitespace-nowrap self-start sm:self-auto"
                                >
                                    {isPlanLoading ? "Retrying..." : "Retry Full plan"}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* 2. Full Improvement Plan Output */}
                    {aiPlan && (
                        <div className="glass-card p-6 space-y-6">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-100">
                                <div>
                                    <h4 className="text-base font-bold text-slate-900 flex items-center gap-2">
                                        <span>📋</span> Full Improvement Plan
                                    </h4>
                                    {aiPlan.serp_used && aiPlan.serp_query && (
                                        <div className="space-y-1.5 mt-1">
                                            <p className="text-xs text-slate-500">
                                                Google data used: search &apos;{aiPlan.serp_query}&apos;{aiPlan.serp_market ? ` (${formatMarketInWords(aiPlan.serp_market)})` : ""} · {aiPlan.serp_paa_found ?? 0} real Google questions found · sources listed below
                                                {" "}
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setIsEditingQuery(!isEditingQuery);
                                                        if (!customQuery) setCustomQuery(aiPlan.serp_query || "");
                                                    }}
                                                    className="text-xs text-red-600 hover:text-red-700 underline font-medium ml-1 transition-colors cursor-pointer"
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
                                        className="text-xs px-3 py-1.5 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1.5"
                                    >
                                        <span>📥</span>
                                        <span>Copy plan as Markdown</span>
                                    </button>
                                </div>
                            </div>

                            {/* Warnings */}
                            {aiPlan.warnings && aiPlan.warnings.length > 0 && (
                                <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl space-y-1">
                                    <div className="text-xs font-semibold text-amber-900 flex items-center gap-1.5">
                                        <span>⚠️</span> Warnings &amp; Actions Required:
                                    </div>
                                    <ul className="text-xs text-amber-800 list-disc list-inside space-y-0.5 pl-1">
                                        {aiPlan.warnings.map((w, idx) => (
                                            <li key={idx}>{w}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {/* Inconsistencies found on the page */}
                            {aiPlan.inconsistencies && aiPlan.inconsistencies.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                            <span>⚖️ Inconsistencies found on the page</span>
                                            <span className="text-xs font-normal text-slate-400">({aiPlan.inconsistencies.length})</span>
                                        </h4>
                                        <p className="text-xs text-slate-500 mt-0.5">
                                            The page contradicts itself here. Pick one version and use it everywhere, so AI engines extract a single answer.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.inconsistencies.map((inc, i) => (
                                            <div key={i} className="p-3.5 rounded-xl bg-amber-50/60 border border-amber-200 space-y-2 text-xs">
                                                <div className="font-semibold text-amber-900 flex items-center gap-1.5">
                                                    <span>🔍</span> {inc.issue}
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">Conflicting values:</span>
                                                    {inc.values.map((val, vIdx) => (
                                                        <span key={vIdx} className="px-2 py-0.5 rounded bg-white text-rose-700 border border-rose-200 font-mono text-[11px]">
                                                            &ldquo;{val}&rdquo;
                                                        </span>
                                                    ))}
                                                </div>
                                                <div className="p-2.5 rounded-lg bg-white/80 border border-slate-200 text-slate-700">
                                                    <strong className="text-slate-900">Recommendation: </strong>
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
                                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                            <span>❓ Questions your page should answer</span>
                                            <span className="text-xs font-normal text-slate-400">({aiPlan.questions_to_answer.length})</span>
                                        </h4>
                                        <p className="text-xs text-slate-500 mt-0.5">
                                            Add these as an FAQ block. Short, direct answers are what AI engines quote.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.questions_to_answer.map((q, i) => (
                                            <div key={i} className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
                                                <div className="flex items-start justify-between gap-2 flex-wrap">
                                                    <div className="text-xs font-semibold text-slate-900">
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
                                                                : "bg-amber-50 border border-amber-200 text-amber-800"
                                                        }`}>
                                                            {q.answer_source === "page"
                                                                ? "Info already on the page — rewrite it as a Q&A"
                                                                : "Missing from the page — needs new content"}
                                                        </span>
                                                    </div>
                                                </div>
                                                <p className="text-xs text-slate-700 leading-relaxed bg-white p-2.5 rounded-lg border border-slate-200">
                                                    {q.draft_answer}
                                                </p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Suggested H2 structure */}
                            {aiPlan.suggested_h2_structure && aiPlan.suggested_h2_structure.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                            <span>📑 Suggested H2 structure</span>
                                            <span className="text-xs font-normal text-slate-400">({aiPlan.suggested_h2_structure.length})</span>
                                        </h4>
                                        <p className="text-xs text-slate-500 mt-0.5">
                                            Use these headings to organise the page. &apos;New&apos; means the section has to be written.
                                        </p>
                                    </div>
                                    <div className="divide-y divide-slate-200 rounded-xl border border-slate-200 overflow-hidden bg-white">
                                        {aiPlan.suggested_h2_structure.map((item, idx) => (
                                            <div key={idx} className="p-3.5 flex items-start justify-between gap-3 text-xs">
                                                <div className="space-y-1">
                                                    <div className="font-semibold text-slate-900">
                                                        {item.h2}
                                                    </div>
                                                    <div className="text-slate-500 text-[11px]">
                                                        {item.purpose}
                                                    </div>
                                                </div>
                                                <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded shrink-0 ${
                                                    item.status === "existing"
                                                        ? "bg-slate-100 text-slate-700 border border-slate-200"
                                                        : "bg-red-50 border border-red-200 text-red-700"
                                                }`}>
                                                    {item.status === "existing" ? "Exists — add the heading" : "New — write this section"}
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
                                            <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                                <span>📊 Suggested table: {aiPlan.suggested_table.title}</span>
                                            </h4>
                                            <p className="text-xs text-slate-500 mt-0.5">
                                                Add this table to the page. All values come from the page itself.
                                            </p>
                                        </div>
                                        {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows && (
                                            <button
                                                type="button"
                                                onClick={handleCopyTableHtml}
                                                className="text-xs px-2.5 py-1 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                            >
                                                📋 Copy HTML
                                            </button>
                                        )}
                                    </div>
                                    {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows ? (
                                        <div className="overflow-x-auto border border-slate-200 rounded-xl">
                                            <table className="w-full text-left text-xs">
                                                <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold">
                                                    <tr>
                                                        {aiPlan.suggested_table.headers.map((h, idx) => (
                                                            <th key={idx} className="py-2.5 px-3">{h}</th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-slate-100">
                                                    {aiPlan.suggested_table.rows.map((row, rIdx) => (
                                                        <tr key={rIdx} className="hover:bg-slate-50/50">
                                                            {row.map((cell, cIdx) => (
                                                                <td key={cIdx} className="py-2.5 px-3 text-slate-700">{cell}</td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <p className="text-xs text-slate-600 italic bg-slate-50 p-3 rounded-lg border border-slate-200">
                                            {aiPlan.suggested_table.table_idea}
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* Data that would enrich the text */}
                            {aiPlan.data_opportunities && aiPlan.data_opportunities.length > 0 && (
                                <div className="space-y-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                            <span>💡 Data that would enrich the text</span>
                                            <span className="text-xs font-normal text-slate-400">({aiPlan.data_opportunities.length})</span>
                                        </h4>
                                        <p className="text-xs text-slate-500 mt-0.5">
                                            Information worth adding. No figures are suggested: find them in the type of source shown.
                                        </p>
                                    </div>
                                    <div className="grid gap-2.5">
                                        {aiPlan.data_opportunities.map((item, idx) => (
                                            <div key={idx} className="p-3 rounded-xl bg-slate-50 border border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                                                <span className="text-slate-800">{item.suggestion}</span>
                                                <span className="text-[11px] px-2 py-0.5 rounded bg-white text-slate-600 border border-slate-200 shrink-0 self-start sm:self-auto font-mono">
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
                                            <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                                <span>🔗 Sources to cite or link</span>
                                                <span className="text-xs font-normal text-slate-400">({aiPlan.sources_to_cite.length})</span>
                                            </h4>
                                            <p className="text-xs text-slate-500 mt-0.5">
                                                Real pages that Google ranks or cites for this topic. Link or cite the relevant ones.
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleCopySources}
                                            className="text-xs px-2.5 py-1 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1 shrink-0"
                                        >
                                            {copiedSources ? "✓ Copied" : "📋 Copy list"}
                                        </button>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.sources_to_cite.map((src, idx) => (
                                            <div key={idx} className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2 text-xs">
                                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                                    <a
                                                        href={src.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="font-semibold text-red-600 hover:text-red-700 hover:underline flex items-center gap-1.5"
                                                    >
                                                        <span>🌐</span> {src.title || src.domain}
                                                    </a>
                                                    <div className="flex items-center gap-2 shrink-0">
                                                        <span className="text-[11px] px-2 py-0.5 rounded bg-white text-slate-600 border border-slate-200 font-mono">
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
                                                    <div className="p-2.5 rounded-lg bg-white border border-slate-200 text-slate-600">
                                                        <strong className="text-slate-900">Why: </strong>
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
                                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                                            <span>✍️ Paragraphs to add</span>
                                            <span className="text-xs font-normal text-slate-400">({aiPlan.paragraphs_to_add.length})</span>
                                        </h4>
                                        <p className="text-xs text-slate-500 mt-0.5">
                                            Ready-to-paste paragraphs, written only with facts from the page.
                                        </p>
                                    </div>
                                    <div className="grid gap-3">
                                        {aiPlan.paragraphs_to_add.map((p, idx) => (
                                            <div key={idx} className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
                                                <div className="flex items-center justify-between gap-2">
                                                    <div className="text-xs font-semibold text-slate-900">
                                                        🎯 {p.target_issue}
                                                    </div>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            navigator.clipboard.writeText(p.suggested_text);
                                                            alert("Paragraph copied to clipboard!");
                                                        }}
                                                        className="text-[11px] px-2 py-0.5 bg-white hover:bg-slate-50 border border-slate-200 rounded text-slate-700 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                                    >
                                                        📋 Copy
                                                    </button>
                                                </div>
                                                <p className="text-xs text-slate-800 leading-relaxed bg-white p-2.5 rounded-lg border border-slate-200">
                                                    {p.suggested_text}
                                                </p>
                                                <div className="text-[11px] text-slate-500 italic">
                                                    Placement: {p.placement}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Combined schema */}
                            {aiPlan.combined_schema && (
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="text-sm font-semibold text-slate-900">
                                                Combined schema
                                            </h4>
                                            <p className="text-xs text-slate-500 mt-0.5">
                                                For the developer: paste in the page &lt;head&gt;.
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleCopyCombinedSchema}
                                            className="text-xs px-2.5 py-1 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium transition-all shadow-2xs cursor-pointer flex items-center gap-1"
                                        >
                                            📋 Copy Schema
                                        </button>
                                    </div>
                                    <div className="p-4 bg-slate-900 text-emerald-400 rounded-xl overflow-x-auto max-h-72 font-mono text-xs leading-relaxed">
                                        <pre>{JSON.stringify(aiPlan.combined_schema, null, 2)}</pre>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
