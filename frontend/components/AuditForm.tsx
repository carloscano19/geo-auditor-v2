"use client";

import { useState, useEffect, useRef, FormEvent, useMemo } from "react";
import { Globe, FileText, Target, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

interface AuditFormProps {
    onSubmit: (url: string | null, text: string | null, targetQuery?: string, contentHtml?: string) => void;
    onBatchSubmit?: (urls: string[], targetQuery?: string) => void;
    isLoading: boolean;
    batchProgress?: { completed: number; total: number } | null;
    initialUrl?: string;
    initialMode?: "url" | "text" | "batch";
}

const QUERY_STOP_WORDS = new Set([
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more", "most", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "with", "would", "you", "your", "yours",
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "a", "al", "en", "con", "por",
    "para", "sobre", "entre", "sin", "y", "e", "ni", "o", "u", "pero", "es", "son", "fue", "fueron",
    "ha", "han", "hay", "que", "como", "cual", "cuales", "este", "esta", "estos", "estas", "ese", "esa"
]);

const EDITORIAL_METADATA_REGEX = /^\s*(?:meta\s+title|meta\s+t[ií]tulo|meta\s+description|meta\s+descripci[oó]n|seo\s+title|t[ií]tulo\s+seo|slug|url|focus\s+keyword|focus\s+keyphrase|target\s+keyword|primary\s+keyword|palabra\s+clave(?:\s+(?:principal|objetivo))?|frase\s+clave(?:\s+(?:principal|objetivo))?)(?:\s*[\(\[][^\)\]]*[\)\]]|\s*[:\-–—])+\s*(.*)$/i;

function isEditorialMetadataText(str: string): boolean {
    if (!str) return false;
    const cleaned = str.replace(/\s+([:\-–—])/g, "$1").replace(/\s+/g, " ").trim();
    return EDITORIAL_METADATA_REGEX.test(cleaned);
}

function cleanClientPastedHtml(rawHtml: string): string {
    const parser = new DOMParser();
    const doc = parser.parseFromString(rawHtml, "text/html");

    // Remove technical/non-content tags
    doc.querySelectorAll("script, style, noscript, iframe, svg, form, button, input, textarea, select, option, meta, link, head").forEach(el => el.remove());

    // Convert Word heading classes into real heading elements
    doc.querySelectorAll("p, div").forEach(el => {
        const cls = (el.getAttribute("class") || "").toLowerCase();
        if (cls.includes("msotitle") || cls.includes("msoheading1")) {
            const h1 = doc.createElement("h1");
            h1.innerHTML = el.innerHTML;
            el.replaceWith(h1);
        } else if (cls.includes("msoheading2")) {
            const h2 = doc.createElement("h2");
            h2.innerHTML = el.innerHTML;
            el.replaceWith(h2);
        } else if (cls.includes("msoheading3")) {
            const h3 = doc.createElement("h3");
            h3.innerHTML = el.innerHTML;
            el.replaceWith(h3);
        } else if (cls.includes("msoheading4")) {
            const h4 = doc.createElement("h4");
            h4.innerHTML = el.innerHTML;
            el.replaceWith(h4);
        }
    });

    // Unwrap Google Docs wrapper
    doc.querySelectorAll("[id*='docs-internal-guid']").forEach(el => {
        while (el.firstChild) el.parentNode?.insertBefore(el.firstChild, el);
        el.remove();
    });

    const ALLOWED = new Set([
        "H1", "H2", "H3", "H4", "H5", "H6",
        "P", "UL", "OL", "LI", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD",
        "A", "STRONG", "B", "EM", "I", "BR", "BLOCKQUOTE"
    ]);

    doc.body.querySelectorAll("*").forEach(el => {
        if (!ALLOWED.has(el.tagName)) {
            while (el.firstChild) el.parentNode?.insertBefore(el.firstChild, el);
            el.remove();
        } else {
            if (el.tagName === "A") {
                const href = (el.getAttribute("href") || "").trim();
                if (/^https?:\/\//i.test(href)) {
                    Array.from(el.attributes).forEach(attr => {
                        if (attr.name !== "href") el.removeAttribute(attr.name);
                    });
                } else {
                    while (el.firstChild) el.parentNode?.insertBefore(el.firstChild, el);
                    el.remove();
                }
            } else {
                Array.from(el.attributes).forEach(attr => el.removeAttribute(attr.name));
            }
        }
    });

    return doc.body.innerHTML;
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
    const [hasBodyContent, setHasBodyContent] = useState(false);
    const [batchUrlsText, setBatchUrlsText] = useState("");
    const [targetQuery, setTargetQuery] = useState("");
    const [batchError, setBatchError] = useState<string | null>(null);

    const editorRef = useRef<HTMLDivElement>(null);

    // Formatted paste state (computed dynamically from editor DOM)
    const [formattedStats, setFormattedStats] = useState<{
        h1: number;
        h2: number;
        h3: number;
        lists: number;
        tables: number;
        links: number;
    } | null>(null);

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

    const inspectEditorContent = () => {
        if (!editorRef.current) return;
        const el = editorRef.current;
        const text = el.innerText || "";
        setHasBodyContent(Boolean(text.trim()));

        const isValidHeading = (heading: Element) => {
            const headingText = (heading.textContent || "").trim();
            const parentLi = heading.closest("li");
            const liText = parentLi ? (parentLi.textContent || "").trim() : "";
            return !isEditorialMetadataText(headingText) && !isEditorialMetadataText(liText);
        };

        const h1Count = Array.from(el.querySelectorAll("h1")).filter(isValidHeading).length;
        const h2Count = Array.from(el.querySelectorAll("h2")).filter(isValidHeading).length;
        const h3Count = Array.from(el.querySelectorAll("h3")).filter(isValidHeading).length;

        const listElements = Array.from(el.querySelectorAll("ul, ol"));
        const listCount = listElements.filter(list => {
            const lis = Array.from(list.querySelectorAll("li"));
            if (lis.length === 0) return false;
            return lis.some(li => !isEditorialMetadataText((li.textContent || "").trim()));
        }).length;

        const tableCount = el.querySelectorAll("table").length;
        const linkCount = el.querySelectorAll("a[href]").length;

        const total = h1Count + h2Count + h3Count + listCount + tableCount + linkCount;
        if (total > 0) {
            setFormattedStats({
                h1: h1Count,
                h2: h2Count,
                h3: h3Count,
                lists: listCount,
                tables: tableCount,
                links: linkCount,
            });
        } else {
            setFormattedStats(null);
        }
    };

    const handleBodyPaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
        e.preventDefault();
        const html = e.clipboardData.getData("text/html");
        const text = e.clipboardData.getData("text/plain");

        if (html && html.trim()) {
            const clean = cleanClientPastedHtml(html);
            document.execCommand("insertHTML", false, clean);
        } else if (text) {
            document.execCommand("insertText", false, text);
        }
        setTimeout(inspectEditorContent, 0);
    };

    const handleEditorInput = () => {
        inspectEditorContent();
    };

    const handleConvertToPlainText = () => {
        if (editorRef.current) {
            const plain = editorRef.current.innerText || "";
            editorRef.current.innerText = plain;
            inspectEditorContent();
        }
    };

    const formatStatsSummary = (stats: {
        h1: number;
        h2: number;
        h3: number;
        lists: number;
        tables: number;
        links: number;
    }) => {
        const parts: string[] = [];
        if (stats.h1 > 0) parts.push(`${stats.h1} H1`);
        if (stats.h2 > 0) parts.push(`${stats.h2} H2`);
        if (stats.h3 > 0) parts.push(`${stats.h3} H3`);
        if (stats.lists > 0) parts.push(`${stats.lists} ${stats.lists === 1 ? "list" : "lists"}`);
        if (stats.tables > 0) parts.push(`${stats.tables} ${stats.tables === 1 ? "table" : "tables"}`);
        if (stats.links > 0) parts.push(`${stats.links} ${stats.links === 1 ? "link" : "links"}`);
        return parts.join(" · ");
    };

    const targetQueryWarning = useMemo(() => {
        if (!targetQuery.trim()) return null;
        const rawTokens = targetQuery
            .toLowerCase()
            .replace(/\$/g, "")
            .replace(/['’]s\b/g, "")
            .match(/[a-záéíóúüñ0-9]+(?:-[a-záéíóúüñ0-9]+)*/g) || [];

        const sigTerms = rawTokens.filter(t => t.length > 1 && !QUERY_STOP_WORDS.has(t));
        if (sigTerms.length === 0) return null;

        if (mode === "text") {
            if (!hasBodyContent) return null;
            const bodyText = editorRef.current?.innerText || "";
            const combined = `${title} ${bodyText}`.toLowerCase();
            const anyMatch = sigTerms.some(term => combined.includes(term));
            if (!anyMatch) {
                return "None of the target query terms appear in this content — check the query";
            }
        }
        return null;
    }, [targetQuery, title, hasBodyContent, mode]);

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        const trimmedQuery = targetQuery.trim() || undefined;
        if (mode === "url" && url.trim()) {
            onSubmit(url.trim(), null, trimmedQuery);
        } else if (mode === "text") {
            const el = editorRef.current;
            if (!el) return;
            const editorText = (el.innerText || "").trim();
            if (!editorText) return;

            const editorHtml = (el.innerHTML || "").trim();
            const escapeHtml = (s: string) =>
                s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

            const hasStructure = formattedStats !== null && (
                formattedStats.h1 > 0 ||
                formattedStats.h2 > 0 ||
                formattedStats.h3 > 0 ||
                formattedStats.lists > 0 ||
                formattedStats.tables > 0 ||
                formattedStats.links > 0
            );

            if (hasStructure || /<(h[1-6]|ul|ol|table|a\s+href)/i.test(editorHtml)) {
                const hasH1 = (formattedStats && formattedStats.h1 > 0) || /<h1[\s>]/i.test(editorHtml);
                let combinedHtml = editorHtml;
                if (title.trim() && !hasH1) {
                    combinedHtml = `<h1>${escapeHtml(title.trim())}</h1>\n${editorHtml}`;
                }
                onSubmit(null, null, trimmedQuery, combinedHtml);
            } else {
                const combinedText = title.trim()
                    ? `${title.trim()}\n\n${editorText}`
                    : editorText;
                onSubmit(null, combinedText, trimmedQuery);
            }
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
            {/* Mode Selector */}
            <div className="flex gap-1.5 p-1 bg-surface-2 rounded-control border border-hairline">
                <button
                    type="button"
                    onClick={() => setMode("url")}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 text-xs font-semibold rounded-[6px] transition-all cursor-pointer ${
                        mode === "url"
                            ? "bg-surface text-ink shadow-2xs border border-hairline"
                            : "text-ink-2 hover:text-ink"
                    }`}
                >
                    <Globe className="size-3.5" />
                    <span>Single URL</span>
                </button>
                <button
                    type="button"
                    onClick={() => {
                        setMode("text");
                        setTimeout(inspectEditorContent, 50);
                    }}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 text-xs font-semibold rounded-[6px] transition-all cursor-pointer ${
                        mode === "text"
                            ? "bg-surface text-ink shadow-2xs border border-hairline"
                            : "text-ink-2 hover:text-ink"
                    }`}
                >
                    <FileText className="size-3.5" />
                    <span>Paste Text</span>
                </button>
                <button
                    type="button"
                    onClick={() => setMode("batch")}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 text-xs font-semibold rounded-[6px] transition-all cursor-pointer ${
                        mode === "batch"
                            ? "bg-surface text-ink shadow-2xs border border-hairline"
                            : "text-ink-2 hover:text-ink"
                    }`}
                >
                    <span className="text-micro font-bold px-1.5 py-0.5 rounded bg-accent/10 text-accent">
                        NEW
                    </span>
                    <span>Batch URLs</span>
                </button>
            </div>

            {/* Input Fields based on Mode */}
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
                            placeholder="https://example.com/article-slug"
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
                            Article Title (H1) <span className="text-micro text-ink-3 font-normal lowercase">(optional if included in content)</span>
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
                        <div
                            id="body"
                            ref={editorRef}
                            contentEditable={!isLoading}
                            onPaste={handleBodyPaste}
                            onInput={handleEditorInput}
                            onKeyUp={handleEditorInput}
                            data-placeholder="Paste your article content here (headings, tables, and links will be preserved)..."
                            className="w-full bg-surface-2 border border-hairline rounded-control p-3.5 text-xs font-sans leading-relaxed text-ink focus:outline-none focus:border-accent focus:bg-surface min-h-[180px] max-h-[450px] overflow-y-auto transition-colors whitespace-pre-wrap select-text"
                        />
                        {formattedStats && (
                            <div className="flex items-center justify-between text-xs bg-accent/10 border border-accent/20 rounded-control px-3 py-2 text-ink">
                                <span>
                                    Formatted paste detected: {formatStatsSummary(formattedStats)}
                                </span>
                                <button
                                    type="button"
                                    onClick={handleConvertToPlainText}
                                    className="text-accent underline hover:text-critical ml-2 shrink-0 cursor-pointer text-xs font-medium"
                                >
                                    Use plain text instead
                                </button>
                            </div>
                        )}
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
                {targetQueryWarning && (
                    <p className="text-xs text-warn font-medium mt-1.5 flex items-center gap-1.5">
                        <span>⚠️</span>
                        <span>{targetQueryWarning}</span>
                    </p>
                )}
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
                    (mode === "text" && !hasBodyContent) ||
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
