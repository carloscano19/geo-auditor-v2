"use client";

import { useState, FormEvent } from "react";

interface AuditFormProps {
    onSubmit: (url: string | null, text: string | null, targetQuery?: string) => void;
    onBatchSubmit?: (urls: string[], targetQuery?: string) => void;
    isLoading: boolean;
    batchProgress?: { completed: number; total: number } | null;
}

export default function AuditForm({ onSubmit, onBatchSubmit, isLoading, batchProgress }: AuditFormProps) {
    const [mode, setMode] = useState<"url" | "text" | "batch">("url");
    const [url, setUrl] = useState("");
    const [title, setTitle] = useState("");
    const [body, setBody] = useState("");
    const [batchUrlsText, setBatchUrlsText] = useState("");
    const [targetQuery, setTargetQuery] = useState("");
    const [batchError, setBatchError] = useState<string | null>(null);

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        const trimmedQuery = targetQuery.trim() || undefined;
        if (mode === "url" && url.trim()) {
            onSubmit(url.trim(), null, trimmedQuery);
        } else if (mode === "text" && body.trim()) {
            // Concatenate title + body as HTML for backend
            const combinedHtml = title.trim()
                ? `<h1>${title.trim()}</h1>\n${body.trim()}`
                : body.trim();
            onSubmit(null, combinedHtml, trimmedQuery);
        } else if (mode === "batch") {
            setBatchError(null);
            const lines = batchUrlsText
                .split("\n")
                .map(line => line.trim())
                .filter(line => line.length > 0);

            if (lines.length === 0) {
                setBatchError("Please enter at least one URL.");
                return;
            }
            if (lines.length > 20) {
                setBatchError("Maximum 20 URLs allowed per batch.");
                return;
            }

            // Validate URL formats
            const invalidUrls = lines.filter(u => !/^https?:\/\//i.test(u));
            if (invalidUrls.length > 0) {
                setBatchError(`Invalid URL format: ${invalidUrls[0]} (must start with http:// or https://)`);
                return;
            }

            if (onBatchSubmit) {
                onBatchSubmit(lines, trimmedQuery);
            }
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-6">
            {/* Input Mode Tabs */}
            <div className="flex p-1 bg-surface-border/30 rounded-lg">
                <button
                    type="button"
                    onClick={() => setMode("url")}
                    className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${mode === "url"
                        ? "bg-surface text-text-primary shadow-sm ring-1 ring-black/5 dark:ring-white/5"
                        : "text-text-muted hover:text-text-secondary"
                        }`}
                >
                    URL Analysis
                </button>
                <button
                    type="button"
                    onClick={() => setMode("text")}
                    className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${mode === "text"
                        ? "bg-surface text-text-primary shadow-sm ring-1 ring-black/5 dark:ring-white/5"
                        : "text-text-muted hover:text-text-secondary"
                        }`}
                >
                    Paste Text
                </button>
                <button
                    type="button"
                    onClick={() => setMode("batch")}
                    className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${mode === "batch"
                        ? "bg-surface text-text-primary shadow-sm ring-1 ring-black/5 dark:ring-white/5"
                        : "text-text-muted hover:text-text-secondary"
                        }`}
                >
                    Batch Audit
                </button>
            </div>

            {mode === "url" ? (
                /* URL Input */
                <div className="space-y-2">
                    <label
                        htmlFor="url"
                        className="block text-sm font-medium text-text-secondary"
                    >
                        Target URL
                    </label>
                    <div className="relative">
                        <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                            <span className="text-xl">🌐</span>
                        </div>
                        <input
                            type="url"
                            id="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://example.com/article"
                            className="input-field pl-12"
                            required
                            disabled={isLoading}
                        />
                    </div>
                </div>
            ) : mode === "text" ? (
                /* Text Input - Split into Title + Body */
                <div className="space-y-4">
                    {/* Title Field */}
                    <div className="space-y-2">
                        <label
                            htmlFor="title"
                            className="block text-sm font-medium text-text-secondary"
                        >
                            Article Title (H1)
                        </label>
                        <div className="relative">
                            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                                <span className="text-lg">📝</span>
                            </div>
                            <input
                                type="text"
                                id="title"
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                placeholder="e.g., What Are Fan Tokens and How Do They Work?"
                                className="input-field pl-12"
                                disabled={isLoading}
                            />
                        </div>
                    </div>

                    {/* Body Field */}
                    <div className="space-y-2">
                        <label
                            htmlFor="body"
                            className="block text-sm font-medium text-text-secondary"
                        >
                            Content Body
                        </label>
                        <textarea
                            id="body"
                            value={body}
                            onChange={(e) => setBody(e.target.value)}
                            placeholder="Paste your article content here (without the title)..."
                            className="input-field min-h-[180px] font-mono text-sm leading-relaxed"
                            required
                            disabled={isLoading}
                        />
                    </div>
                </div>
            ) : (
                /* Batch URLs Input */
                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <label
                            htmlFor="batchUrls"
                            className="block text-sm font-medium text-text-secondary"
                        >
                            Target URLs (1 per line)
                        </label>
                        <span className="text-xs text-text-muted">
                            Max 20 URLs
                        </span>
                    </div>
                    <textarea
                        id="batchUrls"
                        value={batchUrlsText}
                        onChange={(e) => setBatchUrlsText(e.target.value)}
                        placeholder="https://example.com/page-1&#10;https://example.com/page-2&#10;https://example.com/page-3"
                        className="input-field min-h-[160px] font-mono text-xs leading-relaxed"
                        required
                        disabled={isLoading}
                    />
                    {batchError && (
                        <p className="text-xs text-score-critical mt-1">
                            {batchError}
                        </p>
                    )}
                </div>
            )}

            {/* Target Query (Optional) */}
            <div className="space-y-2">
                <label
                    htmlFor="targetQuery"
                    className="block text-sm font-medium text-text-secondary"
                >
                    Target query <span className="text-xs text-text-muted font-normal">(optional)</span>
                </label>
                <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                        <span className="text-lg">🎯</span>
                    </div>
                    <input
                        type="text"
                        id="targetQuery"
                        value={targetQuery}
                        onChange={(e) => setTargetQuery(e.target.value)}
                        placeholder="e.g. best running shoes for flat feet"
                        className="input-field pl-12"
                        disabled={isLoading}
                    />
                </div>
            </div>

            {/* Progress Bar (if Batch running) */}
            {isLoading && batchProgress && batchProgress.total > 0 && (
                <div className="space-y-2 p-3 bg-surface rounded-lg border border-surface-border">
                    <div className="flex justify-between text-xs text-text-secondary">
                        <span>Auditing URLs...</span>
                        <span className="font-mono font-bold text-primary">
                            {batchProgress.completed} / {batchProgress.total}
                        </span>
                    </div>
                    <div className="w-full h-2 bg-surface-border/50 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-primary transition-all duration-300"
                            style={{
                                width: `${Math.round((batchProgress.completed / batchProgress.total) * 100)}%`
                            }}
                        />
                    </div>
                </div>
            )}

            {/* Submit Button */}
            <button
                type="submit"
                disabled={
                    isLoading ||
                    (mode === "url" && !url.trim()) ||
                    (mode === "text" && !body.trim()) ||
                    (mode === "batch" && !batchUrlsText.trim())
                }
                className={`w-full btn-primary flex items-center justify-center gap-2 ${isLoading ? "opacity-50 cursor-not-allowed" : ""
                    }`}
            >
                {isLoading ? (
                    <>
                        <svg
                            className="animate-spin h-5 w-5"
                            fill="none"
                            viewBox="0 0 24 24"
                        >
                            <circle
                                className="opacity-25"
                                cx="12"
                                cy="12"
                                r="10"
                                stroke="currentColor"
                                strokeWidth="4"
                            />
                            <path
                                className="opacity-75"
                                fill="currentColor"
                                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                            />
                        </svg>
                        {mode === "batch" ? "Processing Batch..." : "Analyzing..."}
                    </>
                ) : (
                    <>
                        <svg
                            className="h-5 w-5"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                        </svg>
                        {mode === "batch" ? "Run Batch" : "Run Audit"}
                    </>
                )}
            </button>
        </form>
    );
}
