"use client";

import { useState, FormEvent } from "react";

interface AuditFormProps {
    onSubmit: (url: string | null, text: string | null, platform: string) => void;
    isLoading: boolean;
}

export default function AuditForm({ onSubmit, isLoading }: AuditFormProps) {
    const [mode, setMode] = useState<"url" | "text">("url");
    const [url, setUrl] = useState("");
    const [title, setTitle] = useState("");
    const [body, setBody] = useState("");
    const [platform, setPlatform] = useState("universal");

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        if (mode === "url" && url.trim()) {
            onSubmit(url.trim(), null, platform);
        } else if (mode === "text" && body.trim()) {
            // Concatenate title + body as HTML for backend
            const combinedHtml = title.trim()
                ? `<h1>${title.trim()}</h1>\n${body.trim()}`
                : body.trim();
            onSubmit(null, combinedHtml, platform);
        }
    };

    const platforms = [
        { value: "universal", label: "Universal", icon: "🌐" },
        { value: "chatgpt", label: "ChatGPT", icon: "💬" },
        { value: "gemini", label: "Gemini", icon: "✨" },
        { value: "perplexity", label: "Perplexity", icon: "🔍" },
        { value: "copilot", label: "Copilot", icon: "🤖" },
    ];

    return (
        <form onSubmit={handleSubmit} className="space-y-6">
            {/* Input Mode Tabs */}
            <div className="flex p-1 bg-surface-border/30 rounded-lg">
                <button
                    type="button"
                    onClick={() => setMode("url")}
                    className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-all duration-200 ${mode === "url"
                        ? "bg-surface text-text-primary shadow-sm ring-1 ring-black/5 dark:ring-white/5"
                        : "text-text-muted hover:text-text-secondary"
                        }`}
                >
                    URL Analysis
                </button>
                <button
                    type="button"
                    onClick={() => setMode("text")}
                    className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-all duration-200 ${mode === "text"
                        ? "bg-surface text-text-primary shadow-sm ring-1 ring-black/5 dark:ring-white/5"
                        : "text-text-muted hover:text-text-secondary"
                        }`}
                >
                    Paste Text
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
            ) : (
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
            )}

            {/* Platform Selection */}
            <div className="space-y-2">
                <label className="block text-sm font-medium text-text-secondary">
                    Target Platform
                </label>
                <div className="grid grid-cols-5 gap-2">
                    {platforms.map((p) => (
                        <button
                            key={p.value}
                            type="button"
                            onClick={() => setPlatform(p.value)}
                            className={`flex flex-col items-center p-3 rounded-lg border transition-all duration-200 ${platform === p.value
                                ? "border-primary bg-primary/10 text-primary"
                                : "border-surface-border bg-surface hover:border-primary/50 text-text-secondary"
                                }`}
                        >
                            <span className="text-xl mb-1">{p.icon}</span>
                            <span className="text-xs font-medium">{p.label}</span>
                        </button>
                    ))}
                </div>
            </div>

            {/* Submit Button */}
            <button
                type="submit"
                disabled={isLoading || (mode === "url" && !url.trim()) || (mode === "text" && !body.trim())}
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
                        Analyzing...
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
                        Run Audit
                    </>
                )}
            </button>
        </form>
    );
}
