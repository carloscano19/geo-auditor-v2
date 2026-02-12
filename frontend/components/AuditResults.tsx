"use client";

import React from "react";
import apiClient, { type AuditResponse } from "@/lib/api";
import { useState, useEffect } from "react";
import ScoreDisplay from "./ScoreDisplay";
import ScoreBreakdown from "./ScoreBreakdown";

interface AuditResultsProps {
    results: AuditResponse;
    originalText: string;
}

// Parse markdown briefing into visual cards
function parseBriefingToCards(markdown: string): React.ReactNode {
    if (!markdown.trim()) {
        return <p className="text-slate-400 italic">No recommendations generated.</p>;
    }

    // Badge configuration for role tags
    const ROLE_BADGES: Record<string, { label: string; bg: string; text: string; emoji: string }> = {
        'CONTENT': { label: 'CONTENT', bg: 'bg-indigo-100', text: 'text-indigo-800', emoji: '✍️' },
        'TECH': { label: 'TECH', bg: 'bg-gray-200', text: 'text-gray-800', emoji: '⚙️' },
        'AUTHORITY': { label: 'AUTHORITY', bg: 'bg-amber-100', text: 'text-amber-800', emoji: '📊' },
    };

    // Function to extract role tag from title
    const extractRoleTag = (title: string): { role: string | null; cleanTitle: string } => {
        // Match patterns like [✍️ CONTENT], [⚙️ TECH], [📊 AUTHORITY]
        const roleMatch = title.match(/\[?[✍️⚙️📊]?\s*(CONTENT|TECH|AUTHORITY)\]?/i);
        if (roleMatch) {
            const role = roleMatch[1].toUpperCase();
            // Remove the tag from title and clean up residual characters
            let cleanTitle = title
                .replace(/\[?[✍️⚙️📊]?\s*(CONTENT|TECH|AUTHORITY)\]?\s*/gi, '')
                .replace(/^\]\s*/, '') // Remove leading ]
                .replace(/^\[\s*/, '') // Remove leading [
                .replace(/\]\s*$/, '') // Remove trailing ]
                .trim();
            return { role, cleanTitle };
        }
        return { role: null, cleanTitle: title.replace(/^\]\s*/, '').replace(/^\[\s*/, '').trim() };
    };

    // Split by section headers (### [SECTION])
    const sections = markdown.split(/###\s*/).filter(Boolean);

    if (sections.length === 0) {
        // Fallback to plain text if parsing fails
        return <pre className="whitespace-pre-wrap text-slate-300 font-mono text-sm">{markdown}</pre>;
    }

    return sections.map((section, index) => {
        const lines = section.trim().split('\n');
        const titleLine = lines[0] || '';

        // Extract role and clean title
        const { role, cleanTitle } = extractRoleTag(titleLine.replace(/^\[?|\]$/g, '').trim());
        const sectionTitle = cleanTitle || `Issue ${index + 1}`;
        const badgeConfig = role ? ROLE_BADGES[role] : null;

        // Extract components
        let problem = '';
        let instruction = '';
        let references = '';
        let location = '';

        const content = lines.slice(1).join('\n');

        // Parse Problem
        const problemMatch = content.match(/🔴\s*\*?\*?Problem\*?\*?:\s*([\s\S]*?)(?=💡|🔗|📍|$)/i);
        if (problemMatch) problem = problemMatch[1].trim();

        // Parse Instruction
        const instructionMatch = content.match(/💡\s*\*?\*?Instruction\*?\*?:\s*([\s\S]*?)(?=🔗|📍|---|$)/i);
        if (instructionMatch) instruction = instructionMatch[1].trim();

        // Parse References
        const refsMatch = content.match(/🔗\s*\*?\*?References?\*?\*?:\s*([\s\S]*?)(?=📍|---|$)/i);
        if (refsMatch) references = refsMatch[1].trim();

        // Parse Location
        const locMatch = content.match(/📍\s*\*?\*?Location\*?\*?:\s*([\s\S]*?)(?=---|$)/i);
        if (locMatch) location = locMatch[1].trim();

        // Build card content for copying
        const cardContent = [
            sectionTitle && `[${sectionTitle}]`,
            problem && `Problem: ${problem}`,
            instruction && `Instruction: ${instruction}`,
            references && `References: ${references}`,
            location && `Location: ${location}`
        ].filter(Boolean).join('\n');

        return (
            <div key={index} className="bg-slate-800/50 border border-slate-700 rounded-lg shadow-sm overflow-hidden">
                {/* Card Header with Role Badge */}
                <div className="px-4 py-3 bg-slate-800 border-b border-slate-700">
                    <div className="flex justify-between items-start gap-3">
                        <div className="flex flex-col gap-2">
                            {/* Role Badge */}
                            {badgeConfig && (
                                <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold ${badgeConfig.bg} ${badgeConfig.text} w-fit`}>
                                    {badgeConfig.emoji} {badgeConfig.label}
                                </span>
                            )}
                            {/* Clean Title */}
                            <h4 className="font-semibold text-white text-sm">{sectionTitle}</h4>
                        </div>
                        <button
                            onClick={() => {
                                navigator.clipboard.writeText(cardContent);
                            }}
                            className="text-xs px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors flex-shrink-0"
                            title="Copy this card"
                        >
                            📋 Copy
                        </button>
                    </div>
                </div>

                <div className="p-4 space-y-3">
                    {/* Problem - Red */}
                    {problem && (
                        <div className="bg-red-950/50 border border-red-900/50 rounded-md p-3">
                            <div className="flex items-start gap-2">
                                <span className="text-red-400 font-medium text-xs uppercase tracking-wide">🔴 Problem</span>
                            </div>
                            <p className="text-red-200 text-sm mt-1">{problem}</p>
                        </div>
                    )}

                    {/* Instruction - Blue/Green */}
                    {instruction && (
                        <div className="bg-emerald-950/50 border border-emerald-900/50 rounded-md p-3">
                            <div className="flex items-start gap-2">
                                <span className="text-emerald-400 font-medium text-xs uppercase tracking-wide">💡 Instruction</span>
                            </div>
                            <p className="text-emerald-200 text-sm mt-1 whitespace-pre-wrap">{instruction}</p>
                        </div>
                    )}

                    {/* References - Amber */}
                    {references && (
                        <div className="bg-amber-950/50 border border-amber-900/50 rounded-md p-3">
                            <div className="flex items-start gap-2">
                                <span className="text-amber-400 font-medium text-xs uppercase tracking-wide">🔗 References</span>
                            </div>
                            <p className="text-amber-200 text-sm mt-1">{references}</p>
                        </div>
                    )}

                    {/* Location - Badge */}
                    {location && (
                        <div className="flex items-center gap-2 mt-2">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-700 text-slate-300">
                                📍 {location}
                            </span>
                        </div>
                    )}
                </div>
            </div>
        );
    });
}

export default function AuditResults({ results, originalText }: AuditResultsProps) {
    const [optimizedContent, setOptimizedContent] = useState<string | null>(null);
    const [isOptimizing, setIsOptimizing] = useState(false);
    const [showModal, setShowModal] = useState(false);

    const [showApiKey, setShowApiKey] = useState(false);

    // AI Choice and Key Management
    const [aiProvider, setAiProvider] = useState("openai");
    const [apiKey, setApiKey] = useState("");

    // Load from localStorage on mount
    useEffect(() => {
        const savedProvider = localStorage.getItem("geo_auditor_prev_provider");
        const savedKey = localStorage.getItem(`geo_auditor_key_${savedProvider || "openai"}`);
        if (savedProvider) setAiProvider(savedProvider);
        if (savedKey) setApiKey(savedKey);
    }, []);

    const handleCopySummary = () => {
        // Dimension Name Mapping
        const dimensionMap: Record<string, string> = {
            aeo_structure: "AEO Structure",
            evidence_density: "Evidence Density",
            format_citability: "Formatting & Citability",
            infosec_infra: "Infrastructure & Security",
            authority_signals: "Authority Signals",
            metadata_schema: "Metadata & Schema",
            eeat_authority: "E-E-A-T Authority",
            links_verifiability: "Link Verification",
            // Add Title Case converter for others
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

    const handleOptimize = async () => {
        if (!apiKey) {
            alert("Please enter an API Key for the selected provider.");
            return;
        }

        setIsOptimizing(true);
        // Persist key and provider
        localStorage.setItem("geo_auditor_prev_provider", aiProvider);
        localStorage.setItem(`geo_auditor_key_${aiProvider}`, apiKey);

        try {
            const data = await apiClient.optimize({
                content_text: originalText || "No content provided",
                audit_results: results,
                provider: aiProvider,
                api_key: apiKey
            });
            setOptimizedContent(data.optimized_content);
            setShowModal(true);
        } catch (error) {
            console.error("Optimization failed", error);
            alert("Error connecting to optimization service.");
        } finally {
            setIsOptimizing(false);
        }
    };

    return (
        <div className="space-y-8 animate-fade-in">
            {/* Header with URL and Score */}
            <div className="glass-card p-8">
                <div className="flex flex-col lg:flex-row items-center gap-8">
                    {/* Score Circle */}
                    <ScoreDisplay score={results.total_score} label="Citation Score" />

                    {/* Info */}
                    <div className="flex-1 text-center lg:text-left">
                        <div className="flex justify-between items-start">
                            <div>
                                <h2 className="text-2xl font-bold text-text-primary mb-2">
                                    Analysis Result
                                </h2>
                                <p className="text-text-secondary mb-4 break-all">
                                    {results.url}
                                </p>
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
                            <div className="flex flex-col sm:flex-row items-end gap-3">
                                <div className="space-y-1">
                                    <label className="text-[10px] uppercase tracking-wider text-text-muted font-bold">Provider</label>
                                    <select
                                        value={aiProvider}
                                        onChange={(e) => {
                                            const newProvider = e.target.value;
                                            setAiProvider(newProvider);
                                            // Load key for this provider if it exists
                                            setApiKey(localStorage.getItem(`geo_auditor_key_${newProvider}`) || "");
                                        }}
                                        className="block w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:ring-2 focus:ring-purple-500 transition-all outline-none"
                                    >
                                        <option value="openai">OpenAI (GPT-4o)</option>
                                        <option value="gemini">Google Gemini (Pro)</option>
                                        <option value="perplexity">Perplexity (Online)</option>
                                    </select>
                                </div>
                                <div className="space-y-1">
                                    <label className="text-[10px] uppercase tracking-wider text-text-muted font-bold">API Key</label>
                                    <div className="relative">
                                        <input
                                            type={showApiKey ? "text" : "password"}
                                            value={apiKey}
                                            onChange={(e) => setApiKey(e.target.value)}
                                            placeholder={
                                                aiProvider === "openai" ? "sk-..." :
                                                    aiProvider === "gemini" ? "AIza..." : "pplx-..."
                                            }
                                            className="block w-40 px-3 py-2 pr-8 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:ring-2 focus:ring-purple-500 transition-all outline-none"
                                        />
                                        <button
                                            onClick={() => setShowApiKey(!showApiKey)}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                                            title={showApiKey ? "Hide Key" : "Show Key"}
                                        >
                                            {showApiKey ? "👁️" : "👁️‍🗨️"}
                                        </button>
                                    </div>
                                </div>
                                <button
                                    onClick={handleOptimize}
                                    disabled={isOptimizing}
                                    className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-pink-600 rounded-lg hover:opacity-90 disabled:opacity-50 transition-all font-medium text-white shadow-lg h-[38px]"
                                >
                                    {isOptimizing ? (
                                        <>
                                            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                            Optimizing...
                                        </>
                                    ) : (
                                        <>✨ Optimize</>
                                    )}
                                </button>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-4 justify-center lg:justify-start text-sm text-text-muted">
                            <span>
                                ⏱️ {(results.analysis_time_ms / 1000).toFixed(2)}s
                            </span>
                            <span>📊 Version: {results.scoring_version}</span>
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

            {/* Modal for Optimized Content */}
            {showModal && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                    <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
                        <div className="p-4 border-b border-slate-700 flex justify-between items-center bg-slate-800">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                <span>✨</span> AI Optimized Content
                            </h3>
                            <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white p-1">
                                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                        <div className="p-6 overflow-y-auto bg-slate-900 space-y-4">
                            {parseBriefingToCards(optimizedContent || "")}
                        </div>
                        <div className="p-4 border-t border-slate-700 flex justify-end gap-3 bg-slate-800">
                            <button
                                onClick={() => {
                                    navigator.clipboard.writeText(optimizedContent || "");
                                    alert("Copied to clipboard!");
                                }}
                                className="px-4 py-2 border border-slate-600 rounded-lg hover:bg-slate-700 text-white font-medium"
                            >
                                Copy Content
                            </button>
                            <button
                                onClick={() => setShowModal(false)}
                                className="px-4 py-2 bg-blue-600 rounded-lg hover:bg-blue-500 text-white font-medium"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

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

            {/* Note about Phase 1 */}
            <div className="glass-card p-4 border-l-4 border-primary">
                <p className="text-sm text-text-secondary">
                    <strong className="text-primary">Phase 1 & 2 Active:</strong> Evaluating Technical Infrastructure (12%), AEO Structure (18%), and Entity Identification (8%).
                    Upcoming layers: Metadata, Evidence Density, E-E-A-T, etc.
                </p>
            </div>
        </div>
    );
}
