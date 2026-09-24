"use client";

import React from "react";
import type { AuditResponse } from "@/lib/api";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";

interface AuditResultsProps {
    results: AuditResponse;
    originalText?: string;
}

export default function AuditResults({ results }: AuditResultsProps) {
    const handleCopySummary = () => {
        // Dimension Name Mapping
        const dimensionMap: Record<string, string> = {
            technical_infrastructure: "Technical Infrastructure",
            metadata_schema: "Metadata & Schema",
            aeo_structure: "AEO Structure",
            evidence_density: "Evidence Density",
            eeat_authority: "E-E-A-T Authority",
            entity_identification: "Entity Identification",
            freshness: "Freshness & Currency",
            format_citability: "Formatting & Scannability",
            links_verifiability: "Links & Verifiability",
        };

        const getReadableName = (key: string) => {
            return dimensionMap[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        };

        // Find top issues (score < 50)
        const criticalIssues = results.detector_results
            .filter(d => d.score < 50)
            .sort((a, b) => a.score - b.score)
            .slice(0, 3)
            .map(d => getReadableName(d.dimension));

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
                    <ScoreDisplay
                        score={results.total_score}
                        label="Citation Score"
                        sublabel="Measures on-page readiness for AI citation. Off-page factors like organic rankings and brand authority are not included."
                    />

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
        </div>
    );
}
