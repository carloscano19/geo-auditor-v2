"use client";

import React, { useState } from "react";
import { type AuditResponse, type AIFixesResponse, getDimensionDisplayName, apiClient } from "@/lib/api";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";

interface AuditResultsProps {
    results: AuditResponse;
    originalText?: string;
    hideAiFixes?: boolean;
}

export default function AuditResults({ results, hideAiFixes = false }: AuditResultsProps) {
    const [isAiLoading, setIsAiLoading] = useState(false);
    const [aiFixes, setAiFixes] = useState<AIFixesResponse | null>(null);
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
                                    AI Suggested Fixes
                                </h3>
                            </div>
                            <p className="text-xs text-text-muted mt-1">
                                Generate machine-optimized Schema.org JSON-LD and a direct-answer lead paragraph calibrated for AI engines.
                            </p>
                        </div>
                        <button
                            onClick={handleGenerateAIFixes}
                            disabled={isAiLoading}
                            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-900/50 disabled:text-indigo-400/50 text-white rounded-lg text-sm font-medium transition-all shadow-md flex items-center justify-center gap-2 shrink-0"
                        >
                            {isAiLoading ? (
                                <>
                                    <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                                    Generating...
                                </>
                            ) : (
                                <>
                                    <span>⚡</span> Generate fixes
                                </>
                            )}
                        </button>
                    </div>

                    {/* Error display */}
                    {aiError && (
                        <div className="p-3 bg-red-950/50 border border-red-500/40 rounded-lg text-red-300 text-xs">
                            ⚠️ {aiError}
                        </div>
                    )}

                    {/* Results Display */}
                    {aiFixes && (
                        <div className="space-y-6 pt-2">
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
                                    <h4 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                                        <span>Structured Data (Schema.org JSON-LD)</span>
                                    </h4>
                                    <button
                                        onClick={handleCopyJsonLd}
                                        className="text-xs px-2.5 py-1 bg-surface-border hover:bg-slate-700 text-text-secondary rounded flex items-center gap-1 transition-colors"
                                    >
                                        📋 Copy JSON-LD
                                    </button>
                                </div>
                                <div className="relative">
                                    <pre className="p-4 rounded-lg bg-slate-950 border border-surface-border text-xs text-emerald-400 font-mono overflow-x-auto max-h-72">
                                        {JSON.stringify(aiFixes.json_ld, null, 2)}
                                    </pre>
                                </div>
                                <p className="text-[11px] text-text-muted italic">
                                    Paste inside &lt;script type=&quot;application/ld+json&quot;&gt; in the page head. Replace the placeholder values.
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
