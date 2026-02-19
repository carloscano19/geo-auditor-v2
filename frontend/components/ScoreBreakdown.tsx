"use client";

import type { DetectorResult } from "@/lib/api";

interface ScoreBreakdownProps {
    result: DetectorResult;
}

export default function ScoreBreakdown({ result }: ScoreBreakdownProps) {
    const getStatusColor = (status: string) => {
        switch (status) {
            case "green":
                return "bg-score-excellent";
            case "yellow":
                return "bg-score-warning";
            case "red":
                return "bg-score-critical";
            default:
                return "bg-text-muted";
        }
    };

    const getScoreColor = (score: number) => {
        if (score >= 80) return "text-score-excellent";
        if (score >= 60) return "text-score-good";
        if (score >= 40) return "text-score-warning";
        if (score >= 20) return "text-score-poor";
        return "text-score-critical";
    };

    const getScoreBg = (score: number) => {
        if (score >= 80) return "bg-score-excellent/10";
        if (score >= 60) return "bg-score-good/10";
        if (score >= 40) return "bg-score-warning/10";
        if (score >= 20) return "bg-score-poor/10";
        return "bg-score-critical/10";
    };

    // Format dimension name for display
    const formatDimensionName = (name: string) => {
        return name
            .split("_")
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(" ");
    };

    return (
        <div className="glass-card p-6 space-y-6 animate-slide-up">
            {/* Dimension Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div
                        className={`w-3 h-3 rounded-full ${getStatusColor(
                            result.score >= 80 ? "green" : result.score >= 50 ? "yellow" : "red"
                        )}`}
                    />
                    <h3 className="text-lg font-semibold text-text-primary">
                        {formatDimensionName(result.dimension)}
                    </h3>
                </div>
                <div className="flex items-center gap-2">
                    <span
                        className={`text-2xl font-bold ${getScoreColor(result.score)}`}
                    >
                        {Math.round(result.score)}
                    </span>
                    <span className="text-text-muted text-sm">/100</span>
                </div>
            </div>

            {/* Weight & Contribution */}
            <div className="flex items-center gap-4 text-sm text-text-secondary">
                <span>Weight: {(result.weight * 100).toFixed(0)}%</span>
                <span>•</span>
                <span>Contrib: +{result.contribution.toFixed(1)} pts</span>
            </div>

            {/* Sub-dimension Breakdown */}
            <div className="space-y-4">
                {result.breakdown.map((item, index) => {
                    const SUBTITLES: Record<string, string> = {
                        "Power Lead (Entity in Lead)": "Main Entity mentioned in first 150 chars?",
                        "Rule of 60 (Answer First)": "First paragraph answers user intent directly?",
                        "Entity Density": "Frequency of key topics/brands in text.",
                        "Text Walls": "Paragraphs longer than 5 lines (Mobile readability)."
                    };

                    return (
                        <div
                            key={index}
                            className="p-4 bg-surface rounded-lg border border-surface-border transition-all hover:bg-surface/50"
                        >
                            <div className="flex justify-between items-start mb-2">
                                <div className="flex flex-col">
                                    <span className="font-medium text-text-primary text-sm leading-tight">
                                        {item.name}
                                    </span>
                                    {SUBTITLES[item.name] && (
                                        <span className="text-[11px] text-slate-300 font-semibold mt-1 block">
                                            {SUBTITLES[item.name]}
                                        </span>
                                    )}
                                </div>
                                <span
                                    className={`px-2 py-1 rounded text-xs font-bold leading-none ${getScoreBg(
                                        item.raw_score
                                    )} ${getScoreColor(item.raw_score)}`}
                                >
                                    {Math.round(item.raw_score)}
                                </span>
                            </div>

                            {/* Progress bar */}
                            <div className="h-2 bg-surface-border rounded-full overflow-hidden mb-2">
                                <div
                                    className={`h-full rounded-full transition-all duration-500 ${item.raw_score >= 80
                                        ? "bg-score-excellent"
                                        : item.raw_score >= 60
                                            ? "bg-score-good"
                                            : item.raw_score >= 40
                                                ? "bg-score-warning"
                                                : item.raw_score >= 20
                                                    ? "bg-score-poor"
                                                    : "bg-score-critical"
                                        }`}
                                    style={{ width: `${item.raw_score}%` }}
                                />
                            </div>

                            <p className="text-sm text-text-secondary mb-2">{item.explanation}</p>

                            {/* Recommendations */}
                            {item.recommendations.length > 0 && (
                                <div className="mt-3 pt-3 border-t border-surface-border">
                                    <p className="text-xs font-medium text-text-muted mb-2">
                                        Recommendations:
                                    </p>
                                    <ul className="space-y-1">
                                        {item.recommendations.map((rec, recIndex) => (
                                            <li
                                                key={recIndex}
                                                className="text-sm text-primary flex items-start gap-2"
                                            >
                                                <span className="text-primary mt-1">→</span>
                                                <span>{rec}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Debug / Transparency Info */}
            {result.debug_info && (
                <div className="mt-4 pt-4 border-t border-surface-border">
                    {!!result.debug_info.detected_headers && (
                        <div className="mb-3">
                            <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider mb-2">
                                Found Headers (Scope Check):
                            </h4>
                            <div className="flex flex-wrap gap-2">
                                {(result.debug_info.detected_headers as string[]).map((header, i) => (
                                    <span key={i} className="inline-block px-2 py-1 bg-slate-800 text-slate-300 text-xs rounded border border-slate-700">
                                        H2: {header}
                                    </span>
                                ))}
                                {(result.debug_info.detected_headers as string[]).length === 0 && (
                                    <span className="text-xs text-slate-500 italic">No headers found in main content scope.</span>
                                )}
                            </div>
                        </div>
                    )}

                    {!!result.debug_info.detected_entities && (
                        <div>
                            <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider mb-2">
                                Found Entities (Likely topics):
                            </h4>
                            <div className="flex flex-wrap gap-2">
                                {(result.debug_info.detected_entities as string[]).map((ent, i) => (
                                    <span key={i} className="inline-block px-2 py-1 bg-indigo-950/50 text-indigo-300 text-xs rounded border border-indigo-900/50">
                                        🏷️ {ent}
                                    </span>
                                ))}
                                {(result.debug_info.detected_entities as string[]).length === 0 && (
                                    <span className="text-xs text-slate-500 italic">No specific property entities found.</span>
                                )}
                            </div>
                        </div>
                    )}

                    {!!result.debug_info.citation_links && (
                        <div className="mb-3">
                            <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider mb-2">
                                Citation Links (Counted):
                            </h4>
                            <div className="flex flex-col gap-1">
                                {(result.debug_info.citation_links as { url: string; domain: string }[]).map((link, i) => (
                                    <span key={i} className="text-[11px] text-emerald-400 font-mono truncate bg-emerald-950/20 px-2 py-1 rounded border border-emerald-900/30">
                                        🔗 {link.url}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {!!result.debug_info.utility_links && (
                        <div className="mb-3">
                            <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider mb-2">
                                Utility Links (Ignored):
                            </h4>
                            <div className="flex flex-col gap-1">
                                {(result.debug_info.utility_links as { url: string; domain: string }[]).map((link, i) => (
                                    <span key={i} className="text-[11px] text-slate-500 font-mono truncate bg-slate-900/50 px-2 py-1 rounded border border-slate-800">
                                        ⚙️ {link.url}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Errors */}
            {result.errors.length > 0 && (
                <div className="p-4 bg-score-critical/10 border border-score-critical/30 rounded-lg">
                    <p className="text-sm font-medium text-score-critical mb-2">Errors:</p>
                    <ul className="space-y-1 text-sm text-score-critical">
                        {result.errors.map((error, index) => (
                            <li key={index}>• {error}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
