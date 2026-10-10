"use client";

import React, { useState } from "react";
import {
    apiClient,
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
    csvUrl?: string;
    issuesCsvUrl?: string;
    aiEnabled?: boolean;
    onAnalyzeWithAI?: (url: string) => void;
    onRetryFailed?: (urls: string[]) => void;
}

export default function BatchAuditResults({
    batchData,
    issuesCsvUrl,
    aiEnabled = false,
    onAnalyzeWithAI,
    onRetryFailed,
}: BatchAuditResultsProps) {
    const [selectedItem, setSelectedItem] = useState<BatchItemResult | null>(null);
    const [sortDirection, setSortDirection] = useState<"desc" | "asc">("desc");
    const [isDownloadingCsv, setIsDownloadingCsv] = useState(false);
    const [isDownloadingIssues, setIsDownloadingIssues] = useState(false);

    const handleDownloadCsv = async () => {
        if (!batchData.job_id) return;
        try {
            setIsDownloadingCsv(true);
            await apiClient.downloadBatchCsv(batchData.job_id);
        } catch (err) {
            console.error("Failed to download batch CSV:", err);
        } finally {
            setIsDownloadingCsv(false);
        }
    };

    const handleDownloadIssuesCsv = async () => {
        if (!batchData.job_id) return;
        try {
            setIsDownloadingIssues(true);
            await apiClient.downloadBatchIssuesCsv(batchData.job_id);
        } catch (err) {
            console.error("Failed to download issues CSV:", err);
        } finally {
            setIsDownloadingIssues(false);
        }
    };

    const siteWideIssues = batchData.site_wide_issues || [];
    const topicIssues = batchData.issues_by_topic || [];
    const results = [...(batchData.results || [])];

    // Calculate failed URLs for retry button
    const failedItems = results.filter(r => r.status === "error");
    const failedUrls = failedItems.map(r => r.url);

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

    const getScoreBadgeClass = (score: number) => {
        if (score >= 80) return "bg-good-soft text-good border-good/30";
        if (score >= 50) return "bg-warn-soft text-warn border-warn/30";
        return "bg-critical-soft text-critical border-critical/30";
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
                className="p-4 rounded-xl bg-surface-2/60 border border-hairline hover:border-hairline-strong transition-all space-y-3"
            >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-ink text-sm">
                            {displaySubmetric}
                        </span>
                        {isSiteWide && issue.domain && (
                            <span className="text-[11px] px-2 py-0.5 bg-hairline text-ink-2 rounded-md font-mono">
                                {issue.domain}
                            </span>
                        )}
                        <span className="text-[11px] px-2 py-0.5 bg-red-50 text-critical border border-red-200 rounded-md font-mono">
                            {dimLabel}
                        </span>
                        {isSiteWide && (
                            <span className="text-[10px] px-2 py-0.5 bg-amber-50 text-amber-800 border border-amber-200 rounded-md font-semibold uppercase tracking-wider">
                                Site-wide
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                        <span className="text-ink-2 font-medium">
                            {isSiteWide
                                ? `${issue.affected_count} of ${issue.total_domain_pages ?? batchData.total} page${(issue.total_domain_pages ?? batchData.total) === 1 ? "" : "s"}`
                                : `${issue.affected_count} page${issue.affected_count === 1 ? "" : "s"} affected`}
                        </span>
                        <div className="flex items-center gap-2" title={`Impact score: ${issue.impact.toFixed(2)}`}>
                            <span className="text-ink-3 font-mono text-[11px]">
                                Impact: {issue.impact.toFixed(2)}
                            </span>
                            <div className="w-16 h-1.5 bg-hairline rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-critical rounded-full transition-all duration-300"
                                    style={{ width: `${barWidth}%` }}
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Top recommendation */}
                {issue.top_recommendation && (
                    <div className="text-xs text-ink-2 bg-surface p-3 rounded-lg border border-hairline space-y-1.5 leading-relaxed">
                        <div className="flex items-start gap-2">
                            <span className="text-amber-500 text-xs mt-0.5 font-bold">💡</span>
                            <span>{issue.top_recommendation}</span>
                        </div>
                        {issue.recommendation_breakdown && issue.recommendation_breakdown.length > 1 && (
                            <div className="pl-5 space-y-1 text-[11px] text-ink-3">
                                {issue.recommendation_breakdown.slice(1).map((item, rIdx) => (
                                    <div key={rIdx} className="italic">
                                        Also: {item.recommendation}{" "}
                                        <span className="not-italic text-ink-3">
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
                                className={`text-[11px] px-2.5 py-0.5 rounded-lg transition-all max-w-xs truncate flex items-center gap-1 ${
                                    isClickable
                                        ? "bg-surface text-ink-2 hover:text-accent hover:border-accent cursor-pointer border border-hairline shadow-2xs"
                                        : "bg-surface-2 text-ink-3 cursor-default border border-transparent"
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
        <div className="space-y-6 animate-fade-in">
            {/* Header card with summary stats & export actions */}
            <div className="rounded-card border border-hairline bg-surface p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <h2 className="text-xl sm:text-2xl font-bold text-ink tracking-tight">
                            Batch Audit Summary
                        </h2>
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                            batchData.status === "done"
                                ? "bg-good-soft text-good border-good/30"
                                : "bg-warn-soft text-warn border-warn/30"
                        }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${
                                batchData.status === "done" ? "bg-good" : "bg-warn animate-pulse"
                            }`} />
                            {batchData.status === "done" ? "Completed" : "In Progress"}
                        </span>
                    </div>
                    <p className="text-xs sm:text-sm text-ink-3">
                        {batchData.completed} of {batchData.total} URLs audited
                    </p>
                </div>

                <div className="flex items-center gap-2.5 flex-wrap">
                    {failedUrls.length > 0 && onRetryFailed && (
                        <button
                            type="button"
                            onClick={() => onRetryFailed(failedUrls)}
                            className="px-3.5 py-2 btn-default text-critical border-critical/30 bg-critical-soft hover:bg-critical-soft/80 rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer"
                        >
                            <span>🔄</span> Retry Failed ({failedUrls.length})
                        </button>
                    )}

                    <button
                        type="button"
                        onClick={handleDownloadCsv}
                        disabled={isDownloadingCsv}
                        className="px-3.5 py-2 btn-default text-xs h-8 px-3 flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
                    >
                        <span>📥</span> {isDownloadingCsv ? "Exporting..." : "Export CSV"}
                    </button>

                    {(issuesCsvUrl || allIssues.length > 0) && (
                        <button
                            type="button"
                            onClick={handleDownloadIssuesCsv}
                            disabled={isDownloadingIssues}
                            className="px-3.5 py-2 btn-default text-xs h-8 px-3 flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
                        >
                            <span>📋</span> {isDownloadingIssues ? "Exporting..." : "Export Issues"}
                        </button>
                    )}
                </div>
            </div>

            {/* Section 1: Site-wide Issues */}
            {siteWideIssues.length > 0 && (
                <div className="rounded-card border border-hairline bg-surface p-6 border-l-4 border-l-amber-500">
                    <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <div>
                            <h3 className="text-base font-bold text-ink flex items-center gap-2">
                                <span>🌐</span> Site-wide Issues
                            </h3>
                            <p className="text-xs text-ink-3 mt-0.5">
                                Issues tied to the whole domain (e.g. missing About Us or Team pages).
                            </p>
                        </div>
                        <span className="text-xs px-2.5 py-1 bg-amber-50 text-amber-800 border border-amber-200 rounded-md font-mono font-semibold">
                            {siteWideIssues.length} site-wide issue{siteWideIssues.length === 1 ? "" : "s"}
                        </span>
                    </div>

                    <div className="space-y-3">
                        {siteWideIssues.map((issue, idx) => renderIssueCard(issue, idx, true))}
                    </div>
                </div>
            )}

            {/* Section 2: Issues by Topic */}
            <div className="rounded-card border border-hairline bg-surface p-6">
                <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                    <div>
                        <h3 className="text-base font-bold text-ink flex items-center gap-2">
                            <span>🚨</span> Issues by Topic
                        </h3>
                        <p className="text-xs text-ink-3 mt-0.5">
                            Page-level submetrics scoring &lt; 70 grouped across all pages, ranked by impact (weight × affected pages).
                        </p>
                    </div>
                    <span className="text-xs px-2.5 py-1 bg-surface-2 text-ink-2 border border-hairline rounded-md font-mono font-semibold">
                        {topicIssues.length} issue{topicIssues.length === 1 ? "" : "s"} detected
                    </span>
                </div>

                {topicIssues.length === 0 ? (
                    <div className="p-6 text-center text-xs text-ink-3 bg-surface-2 rounded-xl border border-hairline">
                        ✨ No common page-level issues found under 70 points across the audited URLs!
                    </div>
                ) : (
                    <div className="space-y-3">
                        {topicIssues.map((issue, idx) => renderIssueCard(issue, idx, false))}
                    </div>
                )}
            </div>

            {/* Section 3: URLs Overview Table */}
            <div className="rounded-card border border-hairline bg-surface p-6">
                <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                    <div>
                        <h3 className="text-base font-bold text-ink flex items-center gap-2">
                            <span>📄</span> Audited Pages
                        </h3>
                        <p className="text-xs text-ink-3 mt-0.5">
                            Click any row or affected URL chip to view individual audit details below.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={toggleSort}
                        className="text-xs px-3 py-1.5 btn-default text-xs h-7 px-2.5 flex items-center gap-1.5"
                    >
                        <span>Sort Score:</span>
                        <span className="font-bold text-critical font-mono">
                            {sortDirection === "desc" ? "High to Low ↓" : "Low to High ↑"}
                        </span>
                    </button>
                </div>

                <div className="overflow-x-auto border border-hairline rounded-xl">
                    <table className="w-full text-left text-xs">
                        <thead className="bg-surface-2 border-b border-hairline text-ink-3 uppercase tracking-wider text-[10px]">
                            <tr>
                                <th className="py-3 px-3">URL</th>
                                <th className="py-3 px-3">Score</th>
                                <th className="py-3 px-3">Type</th>
                                <th className="py-3 px-3">Lang</th>
                                <th className="py-3 px-3 text-right">Status</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                            {results.map((item, idx) => {
                                const isClickable = item.status === "done" && !!item.result;
                                const isSelected = selectedItem?.url === item.url;
                                return (
                                    <tr
                                        key={idx}
                                        onClick={() => isClickable && setSelectedItem(isSelected ? null : item)}
                                        className={`transition-colors ${
                                            isClickable
                                                ? "cursor-pointer hover:bg-surface-2/60"
                                                : "opacity-60 cursor-not-allowed"
                                        } ${isSelected ? "bg-accent-soft/40" : ""}`}
                                    >
                                        <td className="py-3.5 px-3 max-w-sm">
                                            <div className="font-medium text-ink truncate" title={item.url}>
                                                {item.url}
                                            </div>
                                            {item.error && (
                                                <div className="text-[11px] text-critical mt-0.5 truncate" title={item.error}>
                                                    ⚠️ {item.error}
                                                </div>
                                            )}
                                        </td>
                                        <td className="py-3.5 px-3">
                                            {item.result ? (
                                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold font-mono border ${getScoreBadgeClass(item.result.total_score)}`}>
                                                    {item.result.total_score.toFixed(0)}/100
                                                </span>
                                            ) : (
                                                <span className="text-xs text-ink-3">—</span>
                                            )}
                                        </td>
                                        <td className="py-3.5 px-3 text-ink-2">
                                            {item.result?.content_type
                                                ? getContentTypeDisplayName(item.result.content_type)
                                                : "—"}
                                        </td>
                                        <td className="py-3.5 px-3 text-ink-2 uppercase font-mono">
                                            {item.result?.language ? item.result.language.toUpperCase() : "—"}
                                        </td>
                                        <td className="py-3.5 px-3 text-right">
                                            <div className="flex items-center justify-end gap-2.5">
                                                {item.status === "done" && (
                                                    <>
                                                        <span className="inline-flex items-center gap-1 text-[11px] text-good font-semibold bg-good-soft border border-good/30 px-2 py-0.5 rounded">
                                                            <span className="w-1.5 h-1.5 rounded-full bg-good" />
                                                            Done
                                                        </span>
                                                        {aiEnabled && onAnalyzeWithAI && (
                                                            <button
                                                                type="button"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    onAnalyzeWithAI(item.url);
                                                                }}
                                                                className="text-xs px-2.5 py-1 bg-surface hover:bg-surface-2 border border-hairline text-critical rounded-lg transition-colors flex items-center gap-1 font-medium shadow-2xs cursor-pointer"
                                                                title="Analyze with AI"
                                                            >
                                                                <span>✨</span> Analyze with AI
                                                            </button>
                                                        )}
                                                    </>
                                                )}
                                                {item.status === "running" && (
                                                    <span className="inline-flex items-center gap-1 text-[11px] text-warn font-semibold bg-warn-soft border border-warn/30 px-2 py-0.5 rounded animate-pulse">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-warn" />
                                                        Running...
                                                    </span>
                                                )}
                                                {item.status === "pending" && (
                                                    <span className="text-[11px] text-ink-3 font-medium">Pending</span>
                                                )}
                                                {item.status === "error" && (
                                                    <span className="inline-flex items-center gap-1 text-[11px] text-critical font-semibold bg-red-50 border border-red-200 px-2 py-0.5 rounded">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-critical" />
                                                        Failed
                                                    </span>
                                                )}
                                            </div>
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
                <div id="individual-audit-report" className="pt-4 border-t border-hairline space-y-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="text-lg">🔎</span>
                            <h3 className="text-lg font-bold text-ink tracking-tight">
                                Individual Report: {selectedItem.url}
                            </h3>
                        </div>
                        <button
                            type="button"
                            onClick={() => setSelectedItem(null)}
                            className="px-3 py-1.5 btn-default text-xs h-7 px-2.5 font-semibold"
                        >
                            ✕ Close Report
                        </button>
                    </div>
                    <AuditResults results={selectedItem.result} hideAiFixes={true} />
                </div>
            )}
        </div>
    );
}
