"use client";

import React, { useState } from "react";
import {
    type BatchJobResponse,
    type BatchItemResult,
    type TopicIssue,
    getDimensionDisplayName,
    getContentTypeDisplayName,
} from "@/lib/api";
import AuditResults from "./AuditResults";

interface BatchAuditResultsProps {
    batchData: BatchJobResponse;
    onReset?: () => void;
    csvUrl: string;
    issuesCsvUrl?: string;
}

export default function BatchAuditResults({ batchData, csvUrl, issuesCsvUrl }: BatchAuditResultsProps) {
    const [selectedItem, setSelectedItem] = useState<BatchItemResult | null>(null);
    const [sortDirection, setSortDirection] = useState<"desc" | "asc">("desc");

    const siteWideIssues = batchData.site_wide_issues || [];
    const topicIssues = batchData.issues_by_topic || [];
    const results = [...(batchData.results || [])];

    // Calculate max impact across all issues for the proportional bar
    const allIssues = [...siteWideIssues, ...topicIssues];
    const maxImpact = Math.max(...allIssues.map(i => i.impact), 0.01);

    // Sort results by score
    results.sort((a, b) => {
        const scoreA = a.result ? a.result.total_score : -1;
        const scoreB = b.result ? b.result.total_score : -1;
        return sortDirection === "desc" ? scoreB - scoreA : scoreA - scoreB;
    });

    const toggleSort = () => {
        setSortDirection(prev => (prev === "desc" ? "asc" : "desc"));
    };

    const handleUrlClick = (targetUrl: string) => {
        const item = results.find(r => r.url === targetUrl);
        if (item && item.status === "done" && item.result) {
            setSelectedItem(item);
            setTimeout(() => {
                const el = document.getElementById("individual-audit-report");
                if (el) el.scrollIntoView({ behavior: "smooth" });
            }, 50);
        }
    };

    const renderIssueCard = (issue: TopicIssue, idx: number, isSiteWide: boolean = false) => {
        const displaySubmetric = issue.submetric === "Entity Depth (E-E-A-T)"
            ? "Author/Publisher Schema"
            : issue.submetric;
        const dimLabel = getDimensionDisplayName(issue.dimension);
        const barWidth = Math.min(100, Math.max(8, Math.round((issue.impact / maxImpact) * 100)));

        return (
            <div
                key={idx}
                className="p-4 rounded-lg bg-surface/70 border border-surface-border hover:border-surface-border/80 transition-all space-y-3"
            >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-text-primary text-base">
                            {displaySubmetric}
                        </span>
                        {isSiteWide && issue.domain && (
                            <span className="text-xs px-2 py-0.5 bg-surface-border/50 text-text-secondary rounded-md font-mono">
                                {issue.domain}
                            </span>
                        )}
                        <span className="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded-md font-mono">
                            {dimLabel}
                        </span>
                        {isSiteWide && (
                            <span className="text-[10px] px-2 py-0.5 bg-score-warning/15 text-score-warning rounded-md font-medium uppercase tracking-wider">
                                Site-wide
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                        <span className="text-score-poor font-medium">
                            {isSiteWide
                                ? `${issue.affected_count} of ${issue.total_domain_pages ?? batchData.total} page${(issue.total_domain_pages ?? batchData.total) === 1 ? "" : "s"}${issue.domain ? ` on ${issue.domain}` : ""}`
                                : `${issue.affected_count} page${issue.affected_count === 1 ? "" : "s"} affected`}
                        </span>
                        <div className="flex items-center gap-2" title={`Impact score: ${issue.impact.toFixed(2)}`}>
                            <span className="text-text-muted font-mono">
                                Impact: {issue.impact.toFixed(2)}
                            </span>
                            <div className="w-16 h-1.5 bg-surface-border/60 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-score-poor rounded-full transition-all duration-300"
                                    style={{ width: `${barWidth}%` }}
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Top recommendation and breakdown */}
                {issue.top_recommendation && (
                    <div className="text-sm text-text-secondary bg-background/50 p-2.5 rounded border border-surface-border/40 space-y-1.5">
                        <div className="flex items-start gap-2">
                            <span className="text-score-warning text-xs mt-0.5">💡</span>
                            <span>{issue.top_recommendation}</span>
                        </div>
                        {issue.recommendation_breakdown && issue.recommendation_breakdown.length > 1 && (
                            <div className="pl-5 space-y-1 text-xs text-text-muted">
                                {issue.recommendation_breakdown.slice(1).map((item, rIdx) => (
                                    <div key={rIdx} className="italic">
                                        Also: {item.recommendation}{" "}
                                        <span className="not-italic text-text-muted/80">
                                            ({item.page_count} page{item.page_count === 1 ? "" : "s"})
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Clickable Affected URLs Chips */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                    {issue.affected_urls.map((u: string, uIdx: number) => {
                        const targetItem = results.find(r => r.url === u);
                        const isClickable = targetItem?.status === "done" && !!targetItem?.result;
                        return (
                            <button
                                key={uIdx}
                                type="button"
                                onClick={() => handleUrlClick(u)}
                                disabled={!isClickable}
                                title={u}
                                className={`text-[11px] px-2.5 py-0.5 rounded transition-all max-w-xs truncate flex items-center gap-1 ${
                                    isClickable
                                        ? "bg-surface-border/40 text-text-secondary hover:bg-primary/20 hover:text-primary cursor-pointer border border-transparent hover:border-primary/30"
                                        : "bg-surface-border/20 text-text-muted cursor-default"
                                }`}
                            >
                                <span className="opacity-70">🔗</span>
                                <span className="truncate">{u.replace(/^https?:\/\//, "")}</span>
                            </button>
                        );
                    })}
                </div>
            </div>
        );
    };

    return (
        <div className="space-y-8 animate-fade-in">
            {/* Header with summary stats & CSV download buttons */}
            <div className="glass-card p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold text-text-primary mb-1">
                        Batch Audit Summary
                    </h2>
                    <p className="text-sm text-text-secondary">
                        {batchData.completed} of {batchData.total} URLs audited • {batchData.status === "done" ? "Completed" : "In Progress"}
                    </p>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                    <a
                        href={csvUrl}
                        download
                        className="btn-secondary text-sm flex items-center gap-2 px-4 py-2"
                    >
                        <span>📥</span> Export CSV
                    </a>
                    {issuesCsvUrl && (
                        <a
                            href={issuesCsvUrl}
                            download
                            className="btn-secondary text-sm flex items-center gap-2 px-4 py-2"
                        >
                            <span>📋</span> Export Issues
                        </a>
                    )}
                </div>
            </div>

            {/* Section 1: Site-wide Issues (Above Issues by Topic) */}
            {siteWideIssues.length > 0 && (
                <div className="glass-card p-6 border-l-4 border-l-score-warning">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                                <span>🌐</span> Site-wide Issues
                            </h3>
                            <p className="text-xs text-text-muted mt-0.5">
                                Issues tied to the whole domain rather than a single page (e.g. missing About Us or Team pages).
                            </p>
                        </div>
                        <span className="text-xs px-2.5 py-1 bg-score-warning/15 text-score-warning rounded-full font-mono font-medium">
                            {siteWideIssues.length} site-wide issue{siteWideIssues.length === 1 ? "" : "s"}
                        </span>
                    </div>

                    <div className="space-y-4">
                        {siteWideIssues.map((issue, idx) => renderIssueCard(issue, idx, true))}
                    </div>
                </div>
            )}

            {/* Section 2: Issues by Topic */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                            <span>🚨</span> Issues by Topic
                        </h3>
                        <p className="text-xs text-text-muted mt-0.5">
                            Page-level submetrics scoring &lt; 70 grouped across all pages, ranked by impact (weight × affected pages).
                        </p>
                    </div>
                    <span className="text-xs px-2.5 py-1 bg-surface-border/50 text-text-secondary rounded-full font-mono">
                        {topicIssues.length} issue{topicIssues.length === 1 ? "" : "s"} detected
                    </span>
                </div>

                {topicIssues.length === 0 ? (
                    <div className="p-6 text-center text-text-muted bg-surface/50 rounded-lg">
                        ✨ No common page-level issues found under 70 points across the audited URLs!
                    </div>
                ) : (
                    <div className="space-y-4">
                        {topicIssues.map((issue, idx) => renderIssueCard(issue, idx, false))}
                    </div>
                )}
            </div>

            {/* Section 3: URLs Overview Table */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                            <span>📄</span> Audited Pages
                        </h3>
                        <p className="text-xs text-text-muted mt-0.5">
                            Click any row or affected URL chip to inspect the individual audit report.
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
                                const isClickable = item.status === "done" && !!item.result;
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
                                        <td className="py-3.5 px-3 text-xs text-text-secondary">
                                            {item.result?.content_type
                                                ? getContentTypeDisplayName(item.result.content_type)
                                                : "—"}
                                        </td>
                                        <td className="py-3.5 px-3 text-xs text-text-secondary uppercase font-mono">
                                            {item.result?.language ? item.result.language.toUpperCase() : "—"}
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

            {/* Section 4: Selected Full Audit Report Expanded View */}
            {selectedItem?.result && (
                <div id="individual-audit-report" className="pt-4 border-t border-surface-border">
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
