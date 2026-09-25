"use client";

import React, { useState } from "react";
import type { BatchJobResponse, BatchItemResult, TopicIssue } from "@/lib/api";
import AuditResults from "./AuditResults";

interface BatchAuditResultsProps {
    batchData: BatchJobResponse;
    onReset?: () => void;
    csvUrl: string;
}

export default function BatchAuditResults({ batchData, csvUrl }: BatchAuditResultsProps) {
    const [selectedItem, setSelectedItem] = useState<BatchItemResult | null>(null);
    const [sortDirection, setSortDirection] = useState<"desc" | "asc">("desc");

    const issues = batchData.issues_by_topic || [];
    const results = [...(batchData.results || [])];

    // Sort results by score
    results.sort((a, b) => {
        const scoreA = a.result ? a.result.total_score : -1;
        const scoreB = b.result ? b.result.total_score : -1;
        return sortDirection === "desc" ? scoreB - scoreA : scoreA - scoreB;
    });

    const toggleSort = () => {
        setSortDirection(prev => (prev === "desc" ? "asc" : "desc"));
    };

    return (
        <div className="space-y-8 animate-fade-in">
            {/* Header with summary stats & CSV download */}
            <div className="glass-card p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold text-text-primary mb-1">
                        Batch Audit Summary
                    </h2>
                    <p className="text-sm text-text-secondary">
                        {batchData.completed} of {batchData.total} URLs audited • {batchData.status === "done" ? "Completed" : "In Progress"}
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <a
                        href={csvUrl}
                        download
                        className="btn-secondary text-sm flex items-center gap-2 px-4 py-2"
                    >
                        <span>📥</span> Export CSV
                    </a>
                </div>
            </div>

            {/* Section 1: Issues by Topic (Highest Priority) */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                            <span>🚨</span> Issues by Topic
                        </h3>
                        <p className="text-xs text-text-muted mt-0.5">
                            Submetrics scoring &lt; 70 grouped across all pages, ranked by impact (weight × affected pages).
                        </p>
                    </div>
                    <span className="text-xs px-2.5 py-1 bg-surface-border/50 text-text-secondary rounded-full font-mono">
                        {issues.length} issue{issues.length === 1 ? "" : "s"} detected
                    </span>
                </div>

                {issues.length === 0 ? (
                    <div className="p-6 text-center text-text-muted bg-surface/50 rounded-lg">
                        ✨ No common issues found under 70 points across the audited URLs!
                    </div>
                ) : (
                    <div className="space-y-4">
                        {issues.map((issue: TopicIssue, idx: number) => {
                            const dimLabel = issue.dimension.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
                            return (
                                <div
                                    key={idx}
                                    className="p-4 rounded-lg bg-surface/70 border border-surface-border hover:border-surface-border/80 transition-all space-y-3"
                                >
                                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                        <div className="flex items-center gap-2">
                                            <span className="font-semibold text-text-primary text-base">
                                                {issue.submetric}
                                            </span>
                                            <span className="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded-md font-mono">
                                                {dimLabel}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-3 text-xs">
                                            <span className="text-score-poor font-medium">
                                                {issue.affected_count} page{issue.affected_count === 1 ? "" : "s"} affected
                                            </span>
                                            <span className="text-text-muted font-mono">
                                                Impact: {issue.impact.toFixed(3)}
                                            </span>
                                        </div>
                                    </div>

                                    {/* Top recommendation */}
                                    {issue.top_recommendation && (
                                        <div className="text-sm text-text-secondary bg-background/50 p-2.5 rounded border border-surface-border/40 flex items-start gap-2">
                                            <span className="text-score-warning text-xs mt-0.5">💡</span>
                                            <span>{issue.top_recommendation}</span>
                                        </div>
                                    )}

                                    {/* Affected URLs list (collapsible/scrollable tags) */}
                                    <div className="flex flex-wrap gap-1.5 pt-1">
                                        {issue.affected_urls.map((u: string, uIdx: number) => (
                                            <span
                                                key={uIdx}
                                                className="text-[11px] px-2 py-0.5 rounded bg-surface-border/40 text-text-muted hover:text-text-primary max-w-xs truncate"
                                                title={u}
                                            >
                                                {u.replace(/^https?:\/\//, "")}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Section 2: URLs Overview Table */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                            <span>📄</span> Audited Pages
                        </h3>
                        <p className="text-xs text-text-muted mt-0.5">
                            Click any row to open the complete individual audit report.
                        </p>
                    </div>
                    <button
                        onClick={toggleSort}
                        className="text-xs px-3 py-1.5 bg-surface hover:bg-surface-border/50 border border-surface-border rounded-md text-text-secondary flex items-center gap-1.5 transition-colors"
                    >
                        <span>Sort Score:</span>
                        <span className="font-semibold text-primary">
                            {sortDirection === "desc" ? "High to Low ↓" : "Low to High ↑"}
                        </span>
                    </button>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead>
                            <tr className="border-b border-surface-border text-xs uppercase text-text-muted">
                                <th className="py-3 px-3">URL</th>
                                <th className="py-3 px-3">Score</th>
                                <th className="py-3 px-3">Type</th>
                                <th className="py-3 px-3">Lang</th>
                                <th className="py-3 px-3 text-right">Status</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-border/50">
                            {results.map((item, idx) => {
                                const isClickable = item.status === "done" && item.result;
                                const isSelected = selectedItem?.url === item.url;
                                return (
                                    <tr
                                        key={idx}
                                        onClick={() => isClickable && setSelectedItem(isSelected ? null : item)}
                                        className={`transition-colors ${isClickable
                                            ? "cursor-pointer hover:bg-surface/80"
                                            : "opacity-60 cursor-not-allowed"
                                            } ${isSelected ? "bg-primary/10" : ""}`}
                                    >
                                        <td className="py-3.5 px-3 max-w-sm">
                                            <div className="font-medium text-text-primary truncate" title={item.url}>
                                                {item.url}
                                            </div>
                                            {item.error && (
                                                <div className="text-xs text-score-critical mt-0.5 truncate" title={item.error}>
                                                    ⚠️ {item.error}
                                                </div>
                                            )}
                                        </td>
                                        <td className="py-3.5 px-3">
                                            {item.result ? (
                                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ${item.result.total_score >= 80
                                                    ? "bg-score-excellent/15 text-score-excellent"
                                                    : item.result.total_score >= 50
                                                        ? "bg-score-good/15 text-score-good"
                                                        : "bg-score-poor/15 text-score-poor"
                                                    }`}>
                                                    {item.result.total_score.toFixed(0)}/100
                                                </span>
                                            ) : (
                                                <span className="text-xs text-text-muted">—</span>
                                            )}
                                        </td>
                                        <td className="py-3.5 px-3 text-xs text-text-secondary capitalize">
                                            {item.result?.content_type?.replace(/_/g, " ") || "—"}
                                        </td>
                                        <td className="py-3.5 px-3 text-xs text-text-secondary uppercase">
                                            {item.result?.language || "—"}
                                        </td>
                                        <td className="py-3.5 px-3 text-right">
                                            {item.status === "done" && (
                                                <span className="text-xs text-score-excellent font-medium">Done</span>
                                            )}
                                            {item.status === "running" && (
                                                <span className="text-xs text-primary font-medium animate-pulse">Running...</span>
                                            )}
                                            {item.status === "pending" && (
                                                <span className="text-xs text-text-muted">Pending</span>
                                            )}
                                            {item.status === "error" && (
                                                <span className="text-xs text-score-critical font-medium">Failed</span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Section 3: Selected Full Audit Report Modal / Expanded View */}
            {selectedItem?.result && (
                <div className="pt-4 border-t border-surface-border">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-xl font-bold text-text-primary">
                            Individual Report: {selectedItem.url}
                        </h3>
                        <button
                            onClick={() => setSelectedItem(null)}
                            className="btn-secondary text-xs px-3 py-1.5"
                        >
                            ✕ Close Report
                        </button>
                    </div>
                    <AuditResults results={selectedItem.result} />
                </div>
            )}
        </div>
    );
}
