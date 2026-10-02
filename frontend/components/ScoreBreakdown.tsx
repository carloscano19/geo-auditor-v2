"use client";

import { useState } from "react";
import { type DetectorResult, getDimensionDisplayName } from "@/lib/api";

interface ScoreBreakdownProps {
    result: DetectorResult;
    isOpen?: boolean;
    onToggle?: () => void;
}

export default function ScoreBreakdown({ result, isOpen, onToggle }: ScoreBreakdownProps) {
    const [internalOpen, setInternalOpen] = useState(false);
    const isExpanded = isOpen !== undefined ? isOpen : internalOpen;

    const handleToggle = () => {
        if (onToggle) {
            onToggle();
        } else {
            setInternalOpen(prev => !prev);
        }
    };

    const getScoreBadgeClass = (score: number) => {
        if (score >= 80) return "bg-emerald-50 border-emerald-200 text-emerald-700";
        if (score >= 60) return "bg-lime-50 border-lime-200 text-lime-700";
        if (score >= 40) return "bg-amber-50 border-amber-200 text-amber-800";
        if (score >= 20) return "bg-orange-50 border-orange-200 text-orange-700";
        return "bg-red-50 border-red-200 text-red-700";
    };

    const getScoreBarClass = (score: number) => {
        if (score >= 80) return "bg-emerald-500";
        if (score >= 60) return "bg-lime-500";
        if (score >= 40) return "bg-amber-500";
        if (score >= 20) return "bg-orange-500";
        return "bg-red-500";
    };

    const getStatusDot = (score: number) => {
        if (score >= 80) return "bg-emerald-500";
        if (score >= 60) return "bg-lime-500";
        if (score >= 40) return "bg-amber-500";
        if (score >= 20) return "bg-orange-500";
        return "bg-red-500";
    };

    const formatDimensionName = (name: string) => {
        return getDimensionDisplayName(name);
    };

    const SUBTITLES: Record<string, string> = {
        "Power Lead (Entity in Lead)": "Main Entity mentioned in first 150 chars?",
        "Rule of 60 (Answer First)": "First paragraph answers user intent directly?",
        "Entity Density": "Frequency of key topics/brands in text.",
        "Text Walls": "Paragraphs longer than 5 lines (Mobile readability).",
        "Source Diversity": "Number of distinct external citation domains (excluding social networks).",
        "Lexical Richness (MTLD)": "Measure of Textual Lexical Diversity across content.",
        "Complete Sentences": "% of substantive paragraphs ending with terminal punctuation.",
        "Content Depth": "Number of in-depth substantive paragraphs (≥ 25 words).",
        "Autonomous Passages": "% of paragraphs that do not depend on previous context.",
        "Full Content Match": "BM25 keyword relevance across the entire article.",
        "Best Passage Match": "Relevance of the most informative matching paragraph.",
        "Opening Paragraph Match": "Presence of core target query terms in opening paragraph."
    };

    return (
        <div className="glass-card overflow-hidden transition-all duration-200">
            {/* Accordion Header / Collapsed View */}
            <button
                type="button"
                onClick={handleToggle}
                className="w-full p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-left hover:bg-slate-50/70 transition-colors cursor-pointer select-none"
                aria-expanded={isExpanded}
            >
                <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${getStatusDot(result.score)}`} />
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-slate-900 text-sm sm:text-base">
                                {formatDimensionName(result.dimension)}
                            </span>
                            <span className="text-[11px] font-mono text-slate-400 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-md">
                                Weight: {(result.weight * 100).toFixed(0)}%
                            </span>
                            <span className="text-[11px] font-mono text-slate-500 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-md">
                                Contrib: +{result.contribution.toFixed(1)} pts
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-4 shrink-0 justify-between sm:justify-end">
                    {/* Dimension Progress Bar */}
                    <div className="w-28 sm:w-36 h-2 bg-slate-100 rounded-full overflow-hidden border border-slate-200/60 hidden xs:block">
                        <div
                            className={`h-full rounded-full transition-all duration-500 ${getScoreBarClass(result.score)}`}
                            style={{ width: `${Math.min(100, Math.max(0, result.score))}%` }}
                        />
                    </div>

                    {/* Score Badge */}
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold border font-mono ${getScoreBadgeClass(result.score)}`}>
                        {Math.round(result.score)} / 100
                    </span>

                    {/* Chevron Icon */}
                    <span className="p-1 text-slate-400 no-print">
                        <svg
                            className={`w-4 h-4 transition-transform duration-200 ${isExpanded ? "rotate-180 text-slate-700" : ""}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                    </span>
                </div>
            </button>

            {/* Accordion Body (Expanded or Print Mode) */}
            <div className={`accordion-content border-t border-slate-100 p-4 sm:p-6 bg-slate-50/40 space-y-5 ${isExpanded ? "block" : "hidden print:block"}`}>
                {/* Submetrics List */}
                <div className="space-y-3">
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Submetrics Breakdown
                    </h4>

                    {result.breakdown.map((item, index) => (
                        <div
                            key={index}
                            className="p-4 bg-white rounded-xl border border-slate-200/80 shadow-2xs space-y-2.5"
                        >
                            <div className="flex justify-between items-start gap-2">
                                <div className="min-w-0 flex-1">
                                    <div className="font-semibold text-slate-900 text-sm leading-tight">
                                        {item.name}
                                    </div>
                                    {SUBTITLES[item.name] && (
                                        <div className="text-[11px] text-slate-500 mt-0.5 leading-snug">
                                            {SUBTITLES[item.name]}
                                        </div>
                                    )}
                                </div>
                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold font-mono border shrink-0 ${getScoreBadgeClass(item.raw_score)}`}>
                                    {Math.round(item.raw_score)}
                                </span>
                            </div>

                            {/* Submetric Progress bar */}
                            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden border border-slate-200/40">
                                <div
                                    className={`h-full rounded-full transition-all duration-500 ${getScoreBarClass(item.raw_score)}`}
                                    style={{ width: `${Math.min(100, Math.max(0, item.raw_score))}%` }}
                                />
                            </div>

                            <p className="text-xs text-slate-600 leading-relaxed pt-0.5">
                                {item.explanation}
                            </p>

                            {/* Recommendations */}
                            {item.recommendations.length > 0 && (
                                <div className="mt-2.5 pt-2.5 border-t border-slate-100">
                                    <p className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                                        Recommended Action:
                                    </p>
                                    <ul className="space-y-1">
                                        {item.recommendations.map((rec, recIndex) => (
                                            <li
                                                key={recIndex}
                                                className="text-xs text-red-700 flex items-start gap-1.5 leading-relaxed bg-red-50/50 p-2 rounded-lg border border-red-100"
                                            >
                                                <span className="text-red-500 font-bold shrink-0">→</span>
                                                <span>{rec}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {/* Debug / Transparency Info */}
                {result.debug_info && (
                    <div className="mt-4 pt-4 border-t border-slate-200/80 space-y-3">
                        {!!result.debug_info.detected_headers && (
                            <div>
                                <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                                    Found Headers (Scope Check):
                                </h5>
                                <div className="flex flex-wrap gap-1.5">
                                    {(result.debug_info.detected_headers as string[]).map((header, i) => (
                                        <span key={i} className="inline-block px-2 py-0.5 bg-white text-slate-700 text-xs rounded-md border border-slate-200">
                                            {header}
                                        </span>
                                    ))}
                                    {(result.debug_info.detected_headers as string[]).length === 0 && (
                                        <span className="text-xs text-slate-400 italic">No headers found in main content scope.</span>
                                    )}
                                </div>
                            </div>
                        )}

                        {!!result.debug_info.detected_entities && (
                            <div>
                                <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                                    Found Entities (Likely topics):
                                </h5>
                                <div className="flex flex-wrap gap-1.5">
                                    {(result.debug_info.detected_entities as string[]).map((ent, i) => (
                                        <span key={i} className="inline-block px-2 py-0.5 bg-slate-100 text-slate-700 text-xs rounded-md border border-slate-200">
                                            🏷️ {ent}
                                        </span>
                                    ))}
                                    {(result.debug_info.detected_entities as string[]).length === 0 && (
                                        <span className="text-xs text-slate-400 italic">No specific property entities found.</span>
                                    )}
                                </div>
                            </div>
                        )}

                        {Array.isArray(result.debug_info.citation_links) && result.debug_info.citation_links.length > 0 && (
                            <div>
                                <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                                    Citation Links (Counted):
                                </h5>
                                <div className="flex flex-col gap-1">
                                    {(result.debug_info.citation_links as (string | { url?: string; domain?: string })[]).map((link, i) => {
                                        const linkStr = typeof link === 'string' ? link : (link?.url || link?.domain || String(link || ''));
                                        return (
                                            <a
                                                key={i}
                                                href={linkStr}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                title={linkStr}
                                                className="text-[11px] text-emerald-700 hover:text-emerald-800 hover:underline font-mono truncate bg-emerald-50/60 px-2 py-1 rounded border border-emerald-200/80 transition-colors block"
                                            >
                                                🔗 {linkStr}
                                            </a>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {Array.isArray(result.debug_info.utility_links) && result.debug_info.utility_links.length > 0 && (
                            <div>
                                <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                                    Utility Links (Ignored):
                                </h5>
                                <div className="flex flex-col gap-1">
                                    {(result.debug_info.utility_links as (string | { url?: string; domain?: string })[]).map((link, i) => {
                                        const linkStr = typeof link === 'string' ? link : (link?.url || link?.domain || String(link || ''));
                                        return (
                                            <span
                                                key={i}
                                                className="text-[11px] text-slate-500 font-mono truncate bg-slate-100 px-2 py-1 rounded border border-slate-200 block"
                                                title={linkStr}
                                            >
                                                ⚙️ {linkStr}
                                            </span>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Errors */}
                {result.errors.length > 0 && (
                    <div className="p-3 bg-red-50 border border-red-200 rounded-xl">
                        <p className="text-xs font-semibold text-red-700 mb-1">Errors:</p>
                        <ul className="space-y-0.5 text-xs text-red-600">
                            {result.errors.map((error, index) => (
                                <li key={index}>• {error}</li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    );
}
