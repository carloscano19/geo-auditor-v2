"use client";

import { useState, useEffect, FormEvent } from "react";
import { Globe, FileText, Target, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

interface AuditFormProps {
    onSubmit: (url: string | null, text: string | null, targetQuery?: string) => void;
    onBatchSubmit?: (urls: string[], targetQuery?: string) => void;
    isLoading: boolean;
    batchProgress?: { completed: number; total: number } | null;
    initialUrl?: string;
    initialMode?: "url" | "text" | "batch";
}

export default function AuditForm({
    onSubmit,
    onBatchSubmit,
    isLoading,
    batchProgress,
    initialUrl = "",
    initialMode = "url",
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
        <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "url" ? (
                /* URL Input */
                <div className="space-y-1.5">
                    <label
                        htmlFor="url"
                        className="block text-micro font-semibold uppercase tracking-wider text-ink-2"
                    >
                        Target URL
                    </label>
                    <div className="relative">
                        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-ink-3">
                            <Globe className="size-4" />
                        </div>
                        <input
                            type="url"
                            id="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://example.com/article"
                            className="input-field pl-10"
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
                            className="block text-micro font-semibold uppercase tracking-wider text-ink-2"
                        >
                            Article Title (H1)
                        </label>
                        <div className="relative">
                            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-ink-3">
                                <FileText className="size-4" />
                            </div>
                            <input
                                type="text"
                                id="title"
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                placeholder="e.g. What Are Fan Tokens and How Do They Work?"
                                className="input-field pl-10"
                                disabled={isLoading}
                            />
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <label
                            htmlFor="body"
                            className="block text-micro font-semibold uppercase tracking-wider text-ink-2"
                        >
                            Content Body
                        </label>
                        <textarea
                            id="body"
                            value={body}
                            onChange={(e) => setBody(e.target.value)}
                            placeholder="Paste your article content here (without the title)..."
                            className="w-full bg-surface-2 border border-hairline rounded-control p-3.5 text-xs font-mono leading-relaxed text-ink placeholder:text-ink-3 focus:outline-none focus:border-accent focus:bg-surface min-h-[160px] transition-colors"
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
                            className="block text-micro font-semibold uppercase tracking-wider text-ink-2"
                        >
                            Target URLs (1 per line)
                        </label>
                        <span className="text-micro font-mono text-ink-3">
                            Max 20 URLs
                        </span>
                    </div>
                    <textarea
                        id="batchUrls"
                        value={batchUrlsText}
                        onChange={(e) => setBatchUrlsText(e.target.value)}
                        placeholder={"https://example.com/page-1\nhttps://example.com/page-2\nhttps://example.com/page-3"}
                        className="w-full bg-surface-2 border border-hairline rounded-control p-3.5 text-xs font-mono leading-relaxed text-ink placeholder:text-ink-3 focus:outline-none focus:border-accent focus:bg-surface min-h-[140px] transition-colors"
                        required
                        disabled={isLoading}
                    />
                    {batchError && (
                        <p className="text-xs text-critical font-medium mt-1">
                            {batchError}
                        </p>
                    )}
                </div>
            )}

            {/* Target Query (Optional) */}
            <div className="space-y-1.5">
                <label
                    htmlFor="targetQuery"
                    className="block text-micro font-semibold uppercase tracking-wider text-ink-2"
                >
                    Target query <span className="text-micro text-ink-3 font-normal lowercase">(optional)</span>
                </label>
                <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-ink-3">
                        <Target className="size-4" />
                    </div>
                    <input
                        type="text"
                        id="targetQuery"
                        value={targetQuery}
                        onChange={(e) => setTargetQuery(e.target.value)}
                        placeholder="e.g. best running shoes for flat feet"
                        className="input-field pl-10"
                        disabled={isLoading}
                    />
                </div>
            </div>

            {/* Batch Progress Bar */}
            {isLoading && batchProgress && batchProgress.total > 0 && (
                <div className="space-y-2 p-3 bg-surface-2 rounded-control border border-hairline">
                    <div className="flex justify-between text-xs text-ink-2 font-medium">
                        <span>Auditing URLs...</span>
                        <span className="font-mono font-bold text-accent">
                            {batchProgress.completed} / {batchProgress.total}
                        </span>
                    </div>
                    <div className="w-full h-1.5 bg-hairline rounded-full overflow-hidden">
                        <div
                            className="h-full bg-accent transition-all duration-300 rounded-full"
                            style={{
                                width: `${Math.round((batchProgress.completed / batchProgress.total) * 100)}%`
                            }}
                        />
                    </div>
                </div>
            )}

            {/* Submit Button */}
            <Button
                type="submit"
                variant="primary"
                disabled={
                    isLoading ||
                    (mode === "url" && !url.trim()) ||
                    (mode === "text" && !body.trim()) ||
                    (mode === "batch" && !batchUrlsText.trim())
                }
                className="w-full"
            >
                {isLoading ? (
                    <>
                        <Loader2 className="size-4 animate-spin" />
                        <span>{mode === "batch" ? "Processing Batch..." : "Analyzing Content..."}</span>
                    </>
                ) : (
                    <>
                        <Play className="size-4 fill-current" />
                        <span>{mode === "batch" ? "Run Batch Audit" : "Run Audit"}</span>
                    </>
                )}
            </Button>
        </form>
    );
}
