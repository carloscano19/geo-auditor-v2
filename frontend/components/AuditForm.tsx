"use client";

import { useState, useEffect, FormEvent } from "react";

interface AuditFormProps {
    onSubmit: (url: string | null, text: string | null, targetQuery?: string) => void;
    onBatchSubmit?: (urls: string[], targetQuery?: string) => void;
    isLoading: boolean;
    batchProgress?: { completed: number; total: number } | null;
    initialUrl?: string;
    initialMode?: "url" | "text" | "batch";
    onModeChange?: (mode: "url" | "text" | "batch") => void;
}

export default function AuditForm({
    onSubmit,
    onBatchSubmit,
    isLoading,
    batchProgress,
    initialUrl = "",
    initialMode = "url",
    onModeChange,
}: AuditFormProps) {
    const [mode, setMode] = useState<"url" | "text" | "batch">(initialMode);
    const [url, setUrl] = useState(initialUrl);
    const [title, setTitle] = useState("");
    const [body, setBody] = useState("");
    const [batchUrlsText, setBatchUrlsText] = useState("");
    const [targetQuery, setTargetQuery] = useState("");
    const [batchError, setBatchError] = useState<string | null>(null);

    useEffect(() => {
        if (initialUrl !== undefined) {
            setUrl(initialUrl);
        }
    }, [initialUrl]);

    useEffect(() => {
        if (initialMode !== undefined) {
            setMode(initialMode);
        }
    }, [initialMode]);

    const handleModeSwitch = (newMode: "url" | "text" | "batch") => {
        setMode(newMode);
        if (onModeChange) onModeChange(newMode);
    };

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        const trimmedQuery = targetQuery.trim() || undefined;
        if (mode === "url" && url.trim()) {
            onSubmit(url.trim(), null, trimmedQuery);
        } else if (mode === "text" && body.trim()) {
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
        <form onSubmit={handleSubmit} className="space-y-5">
            {/* Mode selection pills */}
            <div className="flex p-1 bg-slate-100 rounded-xl border border-slate-200/80">
                <button
                    type="button"
                    onClick={() => handleModeSwitch("url")}
                    className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                        mode === "url"
                            ? "bg-white text-slate-900 shadow-2xs border border-slate-200"
                            : "text-slate-500 hover:text-slate-800"
                    }`}
                >
                    URL Audit
                </button>
                <button
                    type="button"
                    onClick={() => handleModeSwitch("text")}
                    className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                        mode === "text"
                            ? "bg-white text-slate-900 shadow-2xs border border-slate-200"
                            : "text-slate-500 hover:text-slate-800"
                    }`}
                >
                    Paste Text
                </button>
                <button
                    type="button"
                    onClick={() => handleModeSwitch("batch")}
                    className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                        mode === "batch"
                            ? "bg-white text-slate-900 shadow-2xs border border-slate-200"
                            : "text-slate-500 hover:text-slate-800"
                    }`}
                >
                    Batch Audit
                </button>
            </div>

            {mode === "url" ? (
                /* URL Input */
                <div className="space-y-1.5">
                    <label
                        htmlFor="url"
                        className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                    >
                        Target URL
                    </label>
                    <div className="relative">
                        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                            <span className="text-base">🌐</span>
                        </div>
                        <input
                            type="url"
                            id="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://example.com/article"
                            className="input-field pl-11"
                            required
                            disabled={isLoading}
                        />
                    </div>
                </div>
            ) : mode === "text" ? (
                /* Text Input */
                <div className="space-y-4">
                    <div className="space-y-1.5">
                        <label
                            htmlFor="title"
                            className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                        >
                            Article Title (H1)
                        </label>
                        <div className="relative">
                            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                                <span className="text-base">📝</span>
                            </div>
                            <input
                                type="text"
                                id="title"
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                placeholder="e.g. What Are Fan Tokens and How Do They Work?"
                                className="input-field pl-11"
                                disabled={isLoading}
                            />
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <label
                            htmlFor="body"
                            className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                        >
                            Content Body
                        </label>
                        <textarea
                            id="body"
                            value={body}
                            onChange={(e) => setBody(e.target.value)}
                            placeholder="Paste your article content here (without the title)..."
                            className="input-field min-h-[160px] font-mono text-xs leading-relaxed"
                            required
                            disabled={isLoading}
                        />
                    </div>
                </div>
            ) : (
                /* Batch URLs Input */
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                        <label
                            htmlFor="batchUrls"
                            className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                        >
                            Target URLs (1 per line)
                        </label>
                        <span className="text-[11px] font-mono text-slate-400">
                            Max 20 URLs
                        </span>
                    </div>
                    <textarea
                        id="batchUrls"
                        value={batchUrlsText}
                        onChange={(e) => setBatchUrlsText(e.target.value)}
                        placeholder={"https://example.com/page-1\nhttps://example.com/page-2\nhttps://example.com/page-3"}
                        className="input-field min-h-[140px] font-mono text-xs leading-relaxed"
                        required
                        disabled={isLoading}
                    />
                    {batchError && (
                        <p className="text-xs text-red-600 font-medium mt-1">
                            {batchError}
                        </p>
                    )}
                </div>
            )}

            {/* Target Query (Optional) */}
            <div className="space-y-1.5">
                <label
                    htmlFor="targetQuery"
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                >
                    Target query <span className="text-[11px] text-slate-400 font-normal lowercase">(optional)</span>
                </label>
                <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                        <span className="text-base">🎯</span>
                    </div>
                    <input
                        type="text"
                        id="targetQuery"
                        value={targetQuery}
                        onChange={(e) => setTargetQuery(e.target.value)}
                        placeholder="e.g. best running shoes for flat feet"
                        className="input-field pl-11"
                        disabled={isLoading}
                    />
                </div>
            </div>

            {/* Batch Progress Bar */}
            {isLoading && batchProgress && batchProgress.total > 0 && (
                <div className="space-y-2 p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <div className="flex justify-between text-xs text-slate-600 font-medium">
                        <span>Auditing URLs...</span>
                        <span className="font-mono font-bold text-red-600">
                            {batchProgress.completed} / {batchProgress.total}
                        </span>
                    </div>
                    <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-red-600 transition-all duration-300 rounded-full"
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
                className="w-full btn-primary"
            >
                {isLoading ? (
                    <>
                        <svg
                            className="animate-spin h-4 w-4"
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
                        <span>{mode === "batch" ? "Processing Batch..." : "Analyzing Content..."}</span>
                    </>
                ) : (
                    <>
                        <svg
                            className="h-4 w-4"
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
                        <span>{mode === "batch" ? "Run Batch Audit" : "Run Audit"}</span>
                    </>
                )}
            </button>
        </form>
    );
}
