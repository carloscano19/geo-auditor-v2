"use client";

import { useState } from "react";
import AuditForm from "@/components/AuditForm";
import AuditResults from "@/components/AuditResults";
import { apiClient, type AuditResponse } from "@/lib/api";

export default function Home() {
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<AuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastText, setLastText] = useState<string | null>(null);

  const handleAudit = async (url: string | null, text: string | null, platform: string) => {
    setIsLoading(true);
    setError(null);
    setLastText(text); // Guardar el texto para optimización posterior

    try {
      const response = await apiClient.audit({
        url: url || undefined,
        content_text: text || undefined,
        platform_target: platform as "universal" | "chatgpt" | "gemini" | "perplexity" | "copilot",
      });
      setResults(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al analizar la URL");
      setResults(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="split-screen">
      {/* Left Panel - Input (STICKY) */}
      <aside className="bg-surface border-r border-surface-border p-8 flex flex-col sticky top-0 h-screen overflow-y-auto">
        {/* Logo */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold">
            <span className="gradient-text">GEO-AUDITOR</span>
            <span className="text-text-primary"> AI</span>
          </h1>
          <p className="text-sm text-text-muted mt-1">
            LLM Citability Audit Platform
          </p>
        </div>

        {/* Form */}
        <div className="flex-1">
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-text-primary mb-2">
              Analyze Content
            </h2>
            <p className="text-sm text-text-secondary">
              Enter a URL or paste text to evaluate its citation potential in
              ChatGPT, Gemini, Claude, and Perplexity.
            </p>
          </div>

          <AuditForm onSubmit={handleAudit} isLoading={isLoading} />

          {/* Error Display */}
          {error && (
            <div className="mt-4 p-4 bg-score-critical/10 border border-score-critical/30 rounded-lg">
              <p className="text-sm text-score-critical flex items-center gap-2">
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
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                {error}
              </p>
            </div>
          )}
        </div>

        {/* Footer Info */}
        <div className="mt-8 pt-6 border-t border-surface-border">
          <div className="text-xs text-text-muted space-y-2">
            <p className="flex items-center gap-2">
              <span className="w-2 h-2 bg-score-excellent rounded-full" />
              10 Citability Dimensions
            </p>
            <p className="flex items-center gap-2">
              <span className="w-2 h-2 bg-primary rounded-full" />
              Phases 1-2: Infra + NLP Active
            </p>
            <p className="text-text-muted/60 mt-4">
              v2.1 (English) | Feb 2026
            </p>
          </div>
        </div>
      </aside>

      {/* Right Panel - Results */}
      <main className="bg-background p-8 overflow-y-auto">
        {!results && !isLoading && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md">
              <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-surface flex items-center justify-center">
                <svg
                  className="w-12 h-12 text-text-muted"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
                  />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-text-primary mb-2">
                Ready to Audit
              </h2>
              <p className="text-text-secondary">
                Use the left panel to start analyzing content for LLM readiness.
              </p>

              {/* Features List */}
              <div className="mt-8 text-left space-y-3">
                {[
                  "Answer Engine Optimization (AEO) Analysis",
                  "Entity Density & Power Lead Detection",
                  "SSR/CSR Detection for AI Crawlers",
                  "Technical Infrastructure & Speed",
                ].map((feature, index) => (
                  <div
                    key={index}
                    className="flex items-center gap-3 p-3 bg-surface rounded-lg"
                  >
                    <span className="text-primary">✓</span>
                    <span className="text-sm text-text-secondary">{feature}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {isLoading && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 relative">
                <div className="absolute inset-0 border-4 border-surface-border rounded-full" />
                <div className="absolute inset-0 border-4 border-primary rounded-full border-t-transparent animate-spin" />
              </div>
              <h2 className="text-xl font-semibold text-text-primary mb-2">
                Analyzing Content...
              </h2>
              <p className="text-text-secondary">
                Running citability audit...
              </p>
            </div>
          </div>
        )}

        {results && !isLoading && <AuditResults results={results} originalText={lastText || ""} />}
      </main>
    </div>
  );
}
