"use client";

import React, { useState } from "react";
import { type AuditResponse, type AIFixesResponse, type AIPlanResponse, getDimensionDisplayName, apiClient } from "@/lib/api";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";

interface AuditResultsProps {
    results: AuditResponse;
    originalText?: string;
    hideAiFixes?: boolean;
}

export default function AuditResults({ results, hideAiFixes = false }: AuditResultsProps) {
    const [isAiLoading, setIsAiLoading] = useState(false);
    const [isPlanLoading, setIsPlanLoading] = useState(false);
    const [aiFixes, setAiFixes] = useState<AIFixesResponse | null>(null);
    const [aiPlan, setAiPlan] = useState<AIPlanResponse | null>(null);
    const [aiError, setAiError] = useState<string | null>(null);

    const handleGenerateAIFixes = async () => {
        if (!results.ai_context) return;
        setIsAiLoading(true);
        setAiError(null);
        try {
            const data = await apiClient.generateAIFixes(results.ai_context);
            setAiFixes(data);
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to generate AI fixes";
            setAiError(errorMsg);
        } finally {
            setIsAiLoading(false);
        }
    };

    const handleGenerateAIPlan = async () => {
        if (!results.ai_context) return;
        setIsPlanLoading(true);
        setAiError(null);
        try {
            const data = await apiClient.generateAIPlan(results.ai_context);
            setAiPlan(data);
        } catch (err: unknown) {
            const errorMsg = err instanceof Error ? err.message : "Failed to generate AI plan";
            setAiError(errorMsg);
        } finally {
            setIsPlanLoading(false);
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

        if (aiPlan.warnings && aiPlan.warnings.length > 0) {
            lines.push(`## Warnings & Recommendations`);
            aiPlan.warnings.forEach(w => lines.push(`- ⚠️ ${w}`));
            lines.push("");
        }

        if (aiPlan.questions_to_answer && aiPlan.questions_to_answer.length > 0) {
            lines.push(`## Questions to Answer`);
            aiPlan.questions_to_answer.forEach((q, i) => {
                const srcBadge = q.answer_source === "page" ? "[From Page]" : "[Needs New Information]";
                lines.push(`### ${i + 1}. ${q.question} ${srcBadge}`);
                lines.push(`${q.draft_answer}\n`);
            });
        }

        if (aiPlan.suggested_h2_structure && aiPlan.suggested_h2_structure.length > 0) {
            lines.push(`## Suggested H2 Structure`);
            aiPlan.suggested_h2_structure.forEach((h, i) => {
                const statusBadge = h.status === "existing" ? "[Existing]" : "[New]";
                lines.push(`- **H2 ${i + 1}: ${h.h2}** ${statusBadge}`);
                lines.push(`  - *Purpose:* ${h.purpose}`);
            });
            lines.push("");
        }

        if (aiPlan.suggested_table) {
            lines.push(`## Suggested Table: ${aiPlan.suggested_table.title}`);
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
            lines.push(`## Data Opportunities to Enrich Text`);
            aiPlan.data_opportunities.forEach(d => {
                lines.push(`- **${d.suggestion}** (Recommended Source: ${d.source_type})`);
            });
            lines.push("");
        }

        if (aiPlan.inconsistencies && aiPlan.inconsistencies.length > 0) {
            lines.push(`## Inconsistencies Found on the Page`);
            aiPlan.inconsistencies.forEach((inc, i) => {
                lines.push(`### ${i + 1}. ${inc.issue}`);
                lines.push(`- **Conflicting Values:** ${inc.values.map(v => `\`"${v}"\``).join(" vs ")}`);
                lines.push(`- **Recommendation:** ${inc.suggestion}\n`);
            });
        }

        if (aiPlan.paragraphs_to_add && aiPlan.paragraphs_to_add.length > 0) {
            lines.push(`## Paragraphs to Add`);
            aiPlan.paragraphs_to_add.forEach((p, i) => {
                lines.push(`### Paragraph ${i + 1}: Addressing "${p.target_issue}"`);
                lines.push(`*Placement:* ${p.placement}\n`);
                lines.push(`> ${p.suggested_text}\n`);
            });
        }

        if (aiPlan.combined_schema) {
            lines.push(`## Combined Schema.org JSON-LD`);
            lines.push("```json");
            lines.push(JSON.stringify(aiPlan.combined_schema, null, 2));
            lines.push("```\n");
        }

        lines.push(`---\n*Disclaimer: AI-generated suggestions. Review before publishing. They do not affect the Citation Score.*`);

        navigator.clipboard.writeText(lines.join("\n"));
        alert("Full improvement plan copied as Markdown!");
    };

    const handleCopySummary = () => {
        // Find top issues (score < 50)
        const criticalIssues = results.detector_results
            .filter(d => d.score < 50)
            .sort((a, b) => a.score - b.score)
            .slice(0, 3)
            .map(d => getDimensionDisplayName(d.dimension));

        // Find quick wins from recommendations - Deduplicated
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
        <div className="space-y-8 animate-fade-in">
            {/* Header with URL and Score */}
            <div className="glass-card p-8">
                <div className="flex flex-col lg:flex-row items-center gap-8">
                    {/* Score Circle */}
                    <div className="flex flex-col items-center">
                        <ScoreDisplay
                            score={results.total_score}
                            label="Citation Score"
                            sublabel="Measures on-page readiness for AI citation. Off-page factors like organic rankings and brand authority are not included."
                        />
                        {results.score_capped && (
                            <div className="mt-3 px-3 py-2 rounded-md bg-red-950/60 border border-red-500/50 text-red-400 text-xs font-medium text-center max-w-xs">
                                ⚠️ Score capped at 30: {results.cap_reason}
                            </div>
                        )}
                    </div>

                    {/* Info */}
                    <div className="flex-1 text-center lg:text-left">
                        <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
                            <div>
                                <h2 className="text-2xl font-bold text-text-primary mb-2">
                                    Analysis Result
                                </h2>
                                <p className="text-text-secondary mb-4 break-all">
                                    {results.url}
                                </p>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        onClick={handleCopySummary}
                                        className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-md text-slate-300 transition-colors flex items-center gap-2"
                                    >
                                        📋 Copy Summary for Slack
                                    </button>
                                    <button
                                        onClick={() => window.print()}
                                        className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-md text-slate-300 transition-colors flex items-center gap-2"
                                    >
                                        🖨️ Print PDF
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-4 justify-center lg:justify-start text-sm text-text-muted mt-6 pt-4 border-t border-surface-border">
                            <span>
                                ⏱️ {(results.analysis_time_ms / 1000).toFixed(2)}s
                            </span>
                            <span>📊 Version: {results.scoring_version}</span>
                            <span>🌐 Language: {(results.language || "en").toUpperCase()}</span>
                            <span>📄 Type: {results.content_type === "news" ? "News / Press" : results.content_type === "review" ? "Review" : results.content_type === "product" ? "Product" : "Guide / Blog"}</span>
                            <span>
                                📅{" "}
                                {new Date(results.analyzed_at).toLocaleString("en-US", {
                                    dateStyle: "short",
                                    timeStyle: "short",
                                })}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Dimension Results */}
            <div className="space-y-4">
                <h3 className="text-lg font-semibold text-text-primary">
                    Dimension Breakdown
                </h3>
                <div className="grid gap-4">
                    {results.detector_results.map((result, index) => (
                        <ScoreBreakdown key={index} result={result} />
                    ))}
                </div>
            </div>

            {/* AI Suggested Fixes Section (shown only when ai_context is present and not hidden) */}
            {!hideAiFixes && results.ai_context && (
                <div className="glass-card p-6 border-indigo-500/30 bg-slate-900/60 shadow-xl space-y-6">
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-surface-border pb-4">
                        <div>
                            <div className="flex items-center gap-2">
                                <span className="text-xl">✨</span>
                                <h3 className="text-lg font-bold text-text-primary">
                                    AI Optimization & Plan
                                </h3>
                            </div>
                            <p className="text-xs text-text-muted mt-1">
                                Generate machine-optimized Schema.org JSON-LD, direct-answer leads, and comprehensive AEO improvement plans.
                            </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                            <button
                                onClick={handleGenerateAIFixes}
                                disabled={isAiLoading || isPlanLoading}
                                className="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-900/50 disabled:text-indigo-400/50 text-white rounded-lg text-xs sm:text-sm font-medium transition-all shadow-md flex items-center justify-center gap-2"
                            >
                                {isAiLoading ? (
                                    <>
                                        <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                                        Generating fixes...
                                    </>
                                ) : (
                                    <>
                                        <span>⚡</span> Quick fixes
                                    </>
                                )}
                            </button>
                            <button
                                onClick={handleGenerateAIPlan}
                                disabled={isAiLoading || isPlanLoading}
                                className="px-3.5 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:from-purple-900/50 disabled:to-indigo-900/50 disabled:text-purple-300/50 text-white rounded-lg text-xs sm:text-sm font-medium transition-all shadow-md flex items-center justify-center gap-2"
                            >
                                {isPlanLoading ? (
                                    <>
                                        <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                                        Generating plan...
                                    </>
                                ) : (
                                    <>
                                        <span>📋</span> Full improvement plan
                                    </>
                                )}
                            </button>
                        </div>
                    </div>

                    {/* Loading status banner */}
                    {(isAiLoading || isPlanLoading) && (
                        <div className="p-3 bg-indigo-950/40 border border-indigo-500/40 rounded-lg text-indigo-300 text-xs flex items-center gap-2 animate-pulse">
                            <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full" />
                            <span>Generating with AI… this can take up to a minute.</span>
                        </div>
                    )}

                    {/* Error display */}
                    {aiError && (
                        <div className="p-3 bg-red-950/50 border border-red-500/40 rounded-lg text-red-300 text-xs">
                            ⚠️ {aiError}
                        </div>
                    )}

                    {/* Quick Fixes Display */}
                    {aiFixes && (
                        <div className="space-y-6 pt-2">
                            <div className="flex items-center justify-between border-b border-surface-border/50 pb-2">
                                <h4 className="text-sm font-bold text-indigo-300 uppercase tracking-wider flex items-center gap-1.5">
                                    <span>⚡</span> Quick Fixes Result
                                </h4>
                            </div>

                            {/* Warnings */}
                            {aiFixes.warnings && aiFixes.warnings.length > 0 && (
                                <div className="p-3 bg-amber-950/40 border border-amber-500/40 rounded-lg space-y-1">
                                    <div className="text-xs font-semibold text-amber-300 flex items-center gap-1.5">
                                        <span>⚠️</span> Warnings & Actions Required:
                                    </div>
                                    <ul className="text-xs text-amber-200/90 list-disc list-inside space-y-0.5 pl-1">
                                        {aiFixes.warnings.map((w, idx) => (
                                            <li key={idx}>{w}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {/* Schema.org JSON-LD Fix */}
                            <div className="space-y-2">
                                <div className="flex items-center justify-between">
                                    <h4 className="text-sm font-semibold text-text-primary">
                                        Structured Data (Schema.org JSON-LD)
                                    </h4>
                                    <button
                                        onClick={handleCopyJsonLd}
                                        className="text-xs px-2.5 py-1 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                    >
                                        📋 Copy JSON-LD
                                    </button>
                                </div>
                                <div className="relative">
                                    <pre className="p-4 rounded-lg bg-slate-950 border border-surface-border text-xs text-emerald-400 font-mono whitespace-pre-wrap break-words overflow-x-hidden max-h-72 overflow-y-auto">
                                        {JSON.stringify(aiFixes.json_ld, null, 2)}
                                    </pre>
                                </div>
                                <p className="text-[11px] text-text-muted italic">
                                    Paste inside &lt;script type=&quot;application/ld+json&quot;&gt; in the page head. Replace placeholder values.
                                </p>
                            </div>

                            {/* Side-by-side Lead Paragraph Comparison */}
                            <div className="space-y-2">
                                <div className="flex items-center justify-between">
                                    <h4 className="text-sm font-semibold text-text-primary">
                                        Lead Paragraph Optimization
                                    </h4>
                                    <button
                                        onClick={handleCopyLeadParagraph}
                                        className="text-xs px-2.5 py-1 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                    >
                                        📋 Copy Suggested Lead
                                    </button>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {/* Original */}
                                    <div className="p-3.5 rounded-lg bg-surface/50 border border-surface-border">
                                        <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                                            Original Lead Paragraph
                                        </div>
                                        <p className="text-xs text-text-secondary leading-relaxed">
                                            {aiFixes.lead_paragraph.original || (
                                                <span className="italic text-text-muted">No original lead paragraph identified.</span>
                                            )}
                                        </p>
                                    </div>

                                    {/* Suggested */}
                                    <div className="p-3.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30">
                                        <div className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                                            <span>✨</span> Suggested Lead Paragraph (Direct Answer)
                                        </div>
                                        <p className="text-xs text-text-primary leading-relaxed">
                                            {aiFixes.lead_paragraph.suggested}
                                        </p>
                                    </div>
                                </div>

                                {/* Rationale */}
                                {aiFixes.lead_paragraph.rationale && (
                                    <div className="p-3 rounded-lg bg-surface/30 border border-surface-border/60 text-xs text-text-muted">
                                        <strong className="text-text-secondary">Rationale: </strong>
                                        {aiFixes.lead_paragraph.rationale}
                                    </div>
                                )}
                            </div>

                            {/* Fixed Disclaimer */}
                            <div className="pt-2 border-t border-surface-border/60 flex items-center justify-center text-center">
                                <p className="text-[11px] text-text-muted">
                                    ℹ️ AI-generated suggestions. Review before publishing. They do not affect the Citation Score.
                                </p>
                            </div>
                        </div>
                    )}

                    {/* Improvement Plan Display */}
                    {aiPlan && (
                        <div className="space-y-8 pt-2">
                            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-surface-border/50 pb-2">
                                <h4 className="text-sm font-bold text-purple-300 uppercase tracking-wider flex items-center gap-1.5">
                                    <span>📋</span> Full Improvement Plan
                                </h4>
                                <button
                                    onClick={handleCopyPlanMarkdown}
                                    className="text-xs px-3 py-1.5 bg-purple-700/60 hover:bg-purple-600 text-purple-100 rounded-md flex items-center gap-1.5 transition-colors self-start sm:self-auto font-medium"
                                >
                                    📥 Copy plan as Markdown
                                </button>
                            </div>

                            {/* Warnings */}
                            {aiPlan.warnings && aiPlan.warnings.length > 0 && (
                                <div className="p-3 bg-amber-950/40 border border-amber-500/40 rounded-lg space-y-1">
                                    <div className="text-xs font-semibold text-amber-300 flex items-center gap-1.5">
                                        <span>⚠️</span> Warnings & Actions Required:
                                    </div>
                                    <ul className="text-xs text-amber-200/90 list-disc list-inside space-y-0.5 pl-1">
                                        {aiPlan.warnings.map((w, idx) => (
                                            <li key={idx}>{w}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {/* Inconsistencies found on the page */}
                            {aiPlan.inconsistencies && aiPlan.inconsistencies.length > 0 && (
                                <div className="space-y-3">
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>⚖️ Inconsistencies Found on the Page</span>
                                        <span className="text-xs font-normal text-text-muted">({aiPlan.inconsistencies.length})</span>
                                    </h4>
                                    <div className="grid gap-3">
                                        {aiPlan.inconsistencies.map((inc, idx) => (
                                            <div key={idx} className="p-3.5 rounded-lg bg-amber-950/20 border border-amber-500/30 space-y-2 text-xs">
                                                <div className="font-semibold text-amber-300 flex items-center gap-1.5">
                                                    <span>🔍</span> {inc.issue}
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-[11px] text-text-muted uppercase tracking-wider font-medium">Conflicting values:</span>
                                                    {inc.values.map((val, vIdx) => (
                                                        <span key={vIdx} className="px-2 py-0.5 rounded bg-slate-800 text-rose-300 border border-rose-500/30 font-mono text-[11px]">
                                                            &ldquo;{val}&rdquo;
                                                        </span>
                                                    ))}
                                                </div>
                                                <div className="p-2.5 rounded bg-slate-950/50 border border-surface-border/50 text-text-secondary">
                                                    <strong className="text-text-primary">Recommendation: </strong>
                                                    {inc.suggestion}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 1. Questions to answer */}
                            {aiPlan.questions_to_answer && aiPlan.questions_to_answer.length > 0 && (
                                <div className="space-y-3">
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>❓ Questions to Answer</span>
                                        <span className="text-xs font-normal text-text-muted">({aiPlan.questions_to_answer.length})</span>
                                    </h4>
                                    <div className="grid gap-3">
                                        {aiPlan.questions_to_answer.map((q, idx) => (
                                            <div key={idx} className="p-3.5 rounded-lg bg-surface/50 border border-surface-border space-y-2">
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className="text-xs font-semibold text-text-primary">
                                                        {q.question}
                                                    </div>
                                                    <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded ${
                                                        q.answer_source === "page" 
                                                            ? "bg-emerald-950/60 border border-emerald-500/40 text-emerald-400"
                                                            : "bg-amber-950/60 border border-amber-500/40 text-amber-300"
                                                    }`}>
                                                        {q.answer_source === "page" ? "From the page" : "Needs new information"}
                                                    </span>
                                                </div>
                                                <p className="text-xs text-text-secondary leading-relaxed bg-slate-950/40 p-2.5 rounded border border-surface-border/40">
                                                    {q.draft_answer}
                                                </p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 2. Suggested H2 Structure */}
                            {aiPlan.suggested_h2_structure && aiPlan.suggested_h2_structure.length > 0 && (
                                <div className="space-y-3">
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>📑 Suggested H2 Structure</span>
                                        <span className="text-xs font-normal text-text-muted">({aiPlan.suggested_h2_structure.length})</span>
                                    </h4>
                                    <div className="divide-y divide-surface-border rounded-lg border border-surface-border overflow-hidden bg-surface/40">
                                        {aiPlan.suggested_h2_structure.map((item, idx) => (
                                            <div key={idx} className="p-3 flex items-start justify-between gap-3 text-xs">
                                                <div className="space-y-1">
                                                    <div className="font-semibold text-text-primary">
                                                        {item.h2}
                                                    </div>
                                                    <div className="text-text-muted text-[11px]">
                                                        {item.purpose}
                                                    </div>
                                                </div>
                                                <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded shrink-0 ${
                                                    item.status === "existing"
                                                        ? "bg-slate-800 text-slate-300 border border-slate-700"
                                                        : "bg-purple-950/60 border border-purple-500/40 text-purple-300"
                                                }`}>
                                                    {item.status === "existing" ? "Existing" : "New"}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 3. Suggested Table */}
                            {aiPlan.suggested_table && (
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between">
                                        <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                            <span>📊 Suggested Table: {aiPlan.suggested_table.title}</span>
                                        </h4>
                                        {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows && (
                                            <button
                                                onClick={handleCopyTableHtml}
                                                className="text-xs px-2.5 py-1 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                            >
                                                📋 Copy HTML
                                            </button>
                                        )}
                                    </div>

                                    {aiPlan.suggested_table.headers && aiPlan.suggested_table.rows && aiPlan.suggested_table.rows.length > 0 ? (
                                        <div className="rounded-lg border border-surface-border overflow-x-auto bg-slate-950/40">
                                            <table className="w-full text-left text-xs border-collapse">
                                                <thead>
                                                    <tr className="bg-surface/80 border-b border-surface-border text-text-primary font-semibold">
                                                        {aiPlan.suggested_table.headers.map((h, i) => (
                                                            <th key={i} className="p-2.5">{h}</th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-surface-border/50 text-text-secondary">
                                                    {aiPlan.suggested_table.rows.map((row, rIdx) => (
                                                        <tr key={rIdx} className="hover:bg-surface/30">
                                                            {row.map((cell, cIdx) => (
                                                                <td key={cIdx} className="p-2.5">{cell}</td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <div className="p-3.5 rounded-lg bg-surface/40 border border-surface-border text-xs text-text-secondary">
                                            <div className="font-semibold text-text-primary mb-1">Table Idea:</div>
                                            <p>{aiPlan.suggested_table.table_idea || "Create a comparative table with verified structured data."}</p>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* 4. Data that would enrich the text */}
                            {aiPlan.data_opportunities && aiPlan.data_opportunities.length > 0 && (
                                <div className="space-y-3">
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>💡 Data that Would Enrich the Text</span>
                                        <span className="text-xs font-normal text-text-muted">({aiPlan.data_opportunities.length})</span>
                                    </h4>
                                    <div className="grid gap-2.5">
                                        {aiPlan.data_opportunities.map((item, idx) => (
                                            <div key={idx} className="p-3 rounded-lg bg-surface/40 border border-surface-border flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                                                <span className="text-text-primary">{item.suggestion}</span>
                                                <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-text-muted border border-surface-border shrink-0 self-start sm:self-auto">
                                                    Source: {item.source_type}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 5. Paragraphs to add */}
                            {aiPlan.paragraphs_to_add && aiPlan.paragraphs_to_add.length > 0 && (
                                <div className="space-y-3">
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>✍️ Paragraphs to Add</span>
                                        <span className="text-xs font-normal text-text-muted">({aiPlan.paragraphs_to_add.length})</span>
                                    </h4>
                                    <div className="grid gap-3">
                                        {aiPlan.paragraphs_to_add.map((p, idx) => (
                                            <div key={idx} className="p-3.5 rounded-lg bg-surface/50 border border-surface-border space-y-2">
                                                <div className="flex items-center justify-between gap-2">
                                                    <div className="text-xs font-semibold text-purple-300">
                                                        🎯 {p.target_issue}
                                                    </div>
                                                    <button
                                                        onClick={() => {
                                                            navigator.clipboard.writeText(p.suggested_text);
                                                            alert("Paragraph copied to clipboard!");
                                                        }}
                                                        className="text-[11px] px-2 py-0.5 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                                    >
                                                        📋 Copy
                                                    </button>
                                                </div>
                                                <p className="text-xs text-text-primary leading-relaxed bg-slate-950/40 p-2.5 rounded border border-surface-border/40">
                                                    {p.suggested_text}
                                                </p>
                                                <div className="text-[11px] text-text-muted italic">
                                                    Placement: {p.placement}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 6. Combined Schema */}
                            {aiPlan.combined_schema && (
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <h4 className="text-sm font-semibold text-text-primary">
                                            Combined Schema.org (@graph with Article, FAQPage & Organization)
                                        </h4>
                                        <button
                                            onClick={handleCopyCombinedSchema}
                                            className="text-xs px-2.5 py-1 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                        >
                                            📋 Copy Combined Schema
                                        </button>
                                    </div>
                                    <div className="relative">
                                        <pre className="p-4 rounded-lg bg-slate-950 border border-surface-border text-xs text-emerald-400 font-mono whitespace-pre-wrap break-words overflow-x-hidden max-h-72 overflow-y-auto">
                                            {JSON.stringify(aiPlan.combined_schema, null, 2)}
                                        </pre>
                                    </div>
                                </div>
                            )}

                            {/* Fixed Disclaimer */}
                            <div className="pt-2 border-t border-surface-border/60 flex items-center justify-center text-center">
                                <p className="text-[11px] text-text-muted">
                                    ℹ️ AI-generated suggestions. Review before publishing. They do not affect the Citation Score.
                                </p>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Off-page Signals Info Card */}
            <div className="glass-card p-6 border-slate-700/60 bg-slate-900/40">
                <div className="flex items-center gap-2 mb-2">
                    <span className="text-lg">ℹ️</span>
                    <h4 className="text-base font-semibold text-text-primary">
                        Not measured by this tool
                    </h4>
                </div>
                <p className="text-xs text-text-muted mb-4">
                    The Citation Score measures on-page and architectural readiness. Leading AI engines (ChatGPT, Perplexity, Gemini) also consider external off-page signals:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-surface/60 border border-surface-border">
                        <span className="text-base">📊</span>
                        <div>
                            <p className="font-medium text-text-secondary text-xs">Organic ranking position</p>
                            <p className="text-[11px] text-text-muted">Domain authority & traditional search ranking</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-surface/60 border border-surface-border">
                        <span className="text-base">🏷️</span>
                        <div>
                            <p className="font-medium text-text-secondary text-xs">Brand mentions on third-party sites</p>
                            <p className="text-[11px] text-text-muted">Unlinked co-citations and web consensus</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-surface/60 border border-surface-border">
                        <span className="text-base">📱</span>
                        <div>
                            <p className="font-medium text-text-secondary text-xs">Presence on YouTube / Reddit / social</p>
                            <p className="text-[11px] text-text-muted">Community discussion and multimedia footprints</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-surface/60 border border-surface-border">
                        <span className="text-base">🏛️</span>
                        <div>
                            <p className="font-medium text-text-secondary text-xs">Publisher reputation</p>
                            <p className="text-[11px] text-text-muted">Historical accuracy & verified entity graph status</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
