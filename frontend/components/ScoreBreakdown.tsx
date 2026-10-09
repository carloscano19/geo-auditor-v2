"use client";

import { useState } from "react";
import { type DetectorResult, getDimensionDisplayName } from "@/lib/api";
import { ChevronDown } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/badge";

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

    const getScoreBadgeTone = (score: number): BadgeTone => {
        if (score >= 80) return "good";
        if (score >= 60) return "good";
        if (score >= 40) return "warn";
        if (score >= 20) return "critical";
        return "critical";
    };

    const getScoreBarClass = (score: number) => {
        if (score >= 80) return "bg-good";
        if (score >= 60) return "bg-good";
        if (score >= 40) return "bg-warn";
        if (score >= 20) return "bg-critical";
        return "bg-critical";
    };

    const getStatusDot = (score: number) => {
        if (score >= 80) return "bg-good";
        if (score >= 60) return "bg-good";
        if (score >= 40) return "bg-warn";
        if (score >= 20) return "bg-critical";
        return "bg-critical";
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
        <div className="rounded-card border border-hairline bg-surface overflow-hidden transition-colors">
            {/* Accordion Header / Collapsed View */}
            <button
                type="button"
                onClick={handleToggle}
                className="w-full p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-left hover:bg-surface-2 transition-colors cursor-pointer select-none"
                aria-expanded={isExpanded}
            >
                <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className={`size-2.5 rounded-full shrink-0 ${getStatusDot(result.score)}`} />
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-ink text-sm sm:text-[0.9375rem]">
                                {formatDimensionName(result.dimension)}
                            </span>
                            <span className="text-micro font-mono text-ink-3 bg-surface-2 border border-hairline px-2 py-0.5 rounded-control">
                                Weight: {(result.weight * 100).toFixed(0)}%
                            </span>
                            <span className="text-micro font-mono text-ink-2 bg-surface-2 border border-hairline px-2 py-0.5 rounded-control">
                                Contrib: +{result.contribution.toFixed(1)} pts
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-4 shrink-0 justify-between sm:justify-end">
                    {/* Dimension Progress Bar */}
                    <div className="w-28 sm:w-36 h-1.5 bg-surface-2 rounded-full overflow-hidden border border-hairline hidden xs:block">
                        <div
                            className={`h-full rounded-full transition-all duration-500 ${getScoreBarClass(result.score)}`}
                            style={{ width: `${Math.min(100, Math.max(0, result.score))}%` }}
                        />
                    </div>

                    {/* Score Badge */}
                    <Badge tone={getScoreBadgeTone(result.score)} className="font-mono text-xs font-bold px-2.5 py-0.5">
                        {Math.round(result.score)} / 100
                    </Badge>

                    {/* Chevron Icon */}
                    <span className="p-1 text-ink-3 no-print">
                        <ChevronDown
                            className={`size-4 transition-transform duration-200 ${isExpanded ? "rotate-180 text-ink" : ""}`}
                        />
                    </span>
                </div>
            </button>

            {/* Accordion Body (Expanded or Print Mode) */}
            <div className={`accordion-content border-t border-hairline p-4 sm:p-6 bg-surface-2/40 space-y-4 ${isExpanded ? "block" : "hidden print:block"}`}>
                {/* Submetrics List */}
                <div className="space-y-2.5">
                    <h4 className="text-micro font-bold text-ink-3 uppercase tracking-wider">
                        Submetrics Breakdown
                    </h4>

                    {result.breakdown.map((item, index) => (
                        <div
                            key={index}
                            className="p-3.5 bg-surface rounded-control border border-hairline space-y-2"
                        >
                            <div className="flex justify-between items-start gap-2">
                                <div className="min-w-0 flex-1">
                                    <div className="font-semibold text-ink text-xs sm:text-sm leading-tight">
                                        {item.name}
                                    </div>
                                    {SUBTITLES[item.name] && (
                                        <div className="text-micro text-ink-3 mt-0.5 leading-snug">
                                            {SUBTITLES[item.name]}
                                        </div>
                                    )}
                                </div>
                                <Badge tone={getScoreBadgeTone(item.raw_score)} className="font-mono text-xs font-bold px-2 py-0.2 shrink-0">
                                    {Math.round(item.raw_score)}
                                </Badge>
                            </div>

                            {/* Submetric Progress bar */}
                            <div className="w-full h-1 bg-surface-2 rounded-full overflow-hidden">
                                <div
                                    className={`h-full rounded-full transition-all duration-300 ${getScoreBarClass(item.raw_score)}`}
                                    style={{ width: `${Math.min(100, Math.max(0, item.raw_score))}%` }}
                                />
                            </div>

                            {/* Recommendations */}
                            {item.recommendations && item.recommendations.length > 0 && (
                                <div className="mt-2 pt-2 border-t border-hairline/60 space-y-1">
                                    {item.recommendations.map((rec, rIdx) => (
                                        <p key={rIdx} className="text-micro text-ink-2 flex items-start gap-1.5 leading-relaxed">
                                            <span className="text-accent font-bold">›</span>
                                            <span>{rec}</span>
                                        </p>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
