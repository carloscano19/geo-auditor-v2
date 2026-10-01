"use client";

import { useState, useEffect, useRef } from "react";
import AuditForm from "@/components/AuditForm";
import AuditResults from "@/components/AuditResults";
import BatchAuditResults from "@/components/BatchAuditResults";
import { apiClient, type AuditResponse, type BatchJobResponse } from "@/lib/api";

export default function Home() {
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<AuditResponse | null>(null);
  const [batchData, setBatchData] = useState<BatchJobResponse | null>(null);
  const [batchProgress, setBatchProgress] = useState<{ completed: number; total: number } | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState("v2.3");
  const [accessRequired, setAccessRequired] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(true);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [accessCodeInput, setAccessCodeInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Cleanup polling on unmount
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      setIsAuthenticated(false);
      setAuthError("Session expired or invalid code, please enter it again.");
    };

    window.addEventListener("geo_auditor_unauthorized", handleUnauthorized);
    return () => {
      window.removeEventListener("geo_auditor_unauthorized", handleUnauthorized);
    };
  }, []);

  useEffect(() => {
    // 1. Wipe any stored API keys on load
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && (key.startsWith("geo_auditor_key_") || key === "geo_auditor_prev_provider")) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach((k) => localStorage.removeItem(k));
    } catch {
      // Ignore in restricted environments
    }

    // 2. Fetch backend version as single source of truth
    apiClient
      .getVersion()
      .then(async (data) => {
        if (data?.version) setVersion(data.version);
        if (data?.access_required) {
          setAccessRequired(true);
          const storedCode = apiClient.getStoredAccessCode();
          if (storedCode) {
            const check = await apiClient.checkAuth(storedCode);
            if (check.ok) {
              setIsAuthenticated(true);
            } else {
              apiClient.clearStoredAccessCode();
              setIsAuthenticated(false);
            }
          } else {
            setIsAuthenticated(false);
          }
        } else {
          setAccessRequired(false);
          setIsAuthenticated(true);
        }
      })
      .catch(() => {
        // Fallback default
        setIsAuthenticated(true);
      })
      .finally(() => {
        setIsAuthChecking(false);
      });
  }, []);

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!accessCodeInput.trim()) return;
    setIsSubmittingAuth(true);
    setAuthError(null);

    try {
      const res = await apiClient.checkAuth(accessCodeInput.trim());
      if (res.ok) {
        apiClient.setStoredAccessCode(accessCodeInput.trim());
        setIsAuthenticated(true);
        setAccessCodeInput("");
        setAuthError(null);
      } else {
        setAuthError(res.error || "Invalid access code");
      }
    } catch {
      setAuthError("Invalid access code");
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const handleLogout = () => {
    apiClient.clearStoredAccessCode();
    setIsAuthenticated(false);
    setAuthError(null);
    setResults(null);
    setBatchData(null);
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
  };

  const handleAudit = async (url: string | null, text: string | null, targetQuery?: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setIsLoading(true);
    setError(null);
    setBatchData(null);
    setBatchProgress(null);
    setActiveJobId(null);

    try {
      const response = await apiClient.audit({
        url: url || undefined,
        content_text: text || undefined,
        target_query: targetQuery || undefined,
      });
      setResults(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error analyzing content");
      setResults(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleBatchAudit = async (urls: string[], targetQuery?: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setIsLoading(true);
    setError(null);
    setResults(null);
    setBatchData(null);
    setBatchProgress({ completed: 0, total: urls.length });

    try {
      const { job_id } = await apiClient.startBatch({
        urls,
        target_query: targetQuery || undefined,
      });

      setActiveJobId(job_id);

      // Poll every 5 seconds
      const poll = async () => {
        try {
          const status = await apiClient.getBatchStatus(job_id);
          setBatchData(status);
          setBatchProgress({ completed: status.completed, total: status.total });

          if (status.status === "done") {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            setIsLoading(false);
          }
        } catch (pollErr) {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setIsLoading(false);
          setError(pollErr instanceof Error ? pollErr.message : "Failed to poll batch status");
        }
      };

      // Initial check immediately
      await poll();
      pollIntervalRef.current = setInterval(poll, 5000);
    } catch (err) {
      setIsLoading(false);
      setBatchProgress(null);
      setError(err instanceof Error ? err.message : "Failed to initiate batch audit");
    }
  };

  if (isAuthChecking) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-12 h-12 relative">
          <div className="absolute inset-0 border-4 border-surface-border rounded-full" />
          <div className="absolute inset-0 border-4 border-primary rounded-full border-t-transparent animate-spin" />
        </div>
      </div>
    );
  }

  if (accessRequired && !isAuthenticated) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4">
        <div className="w-full max-w-sm bg-surface border border-surface-border rounded-2xl p-8 shadow-2xl">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold">
              <span className="gradient-text">GEO-AUDITOR</span>
              <span className="text-text-primary"> AI</span>
            </h1>
            <p className="text-sm text-text-muted mt-2">
              LLM Citability Audit Platform
            </p>
          </div>

          <form onSubmit={handleAuthSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="access-code"
                className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-2"
              >
                Access code
              </label>
              <input
                id="access-code"
                type="password"
                value={accessCodeInput}
                onChange={(e) => {
                  setAccessCodeInput(e.target.value);
                  if (authError) setAuthError(null);
                }}
                placeholder="Access code"
                autoFocus
                disabled={isSubmittingAuth}
                className="w-full px-4 py-3 rounded-lg bg-surface-dark border border-surface-border text-text-primary placeholder-text-muted focus:outline-none focus:border-primary transition-colors text-sm"
              />
              {authError && (
                <p className="mt-2 text-xs text-score-critical text-center">
                  {authError}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isSubmittingAuth || !accessCodeInput.trim()}
              className="w-full py-3 px-4 rounded-lg bg-primary hover:bg-primary-hover text-white font-medium text-sm transition-all duration-200 shadow-lg shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isSubmittingAuth ? "Checking..." : "Enter"}
            </button>
          </form>
        </div>
      </div>
    );
  }

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

          <AuditForm
            onSubmit={handleAudit}
            onBatchSubmit={handleBatchAudit}
            isLoading={isLoading}
            batchProgress={batchProgress}
          />

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
              {results
                ? `${results.dimensions?.length || 0} Dimensions Evaluated`
                : batchData
                ? `Batch: ${batchData.completed}/${batchData.total} URLs Evaluated`
                : "Up to 11 citability dimensions"}
            </p>
            <p className="text-text-muted/60 mt-4">
              {version} (English)
            </p>
            <p className="text-text-muted/60 mt-2">
              Built by{" "}
              <a
                href="https://www.linkedin.com/in/carlos-cano-fernandez-seo-aso-manager/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:text-primary/80 transition-colors underline"
              >
                Carlos Cano Fernandez
              </a>
            </p>
            {accessRequired && (
              <p className="mt-2">
                <button
                  type="button"
                  onClick={handleLogout}
                  className="text-text-muted/60 hover:text-text-primary transition-colors underline"
                >
                  Log out
                </button>
              </p>
            )}
          </div>
        </div>
      </aside>

      {/* Right Panel - Results */}
      <main className="bg-background p-8 overflow-y-auto">
        {!results && !batchData && !isLoading && (
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

        {isLoading && !batchData && (
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

        {results && !isLoading && <AuditResults results={results} />}

        {batchData && (
          <BatchAuditResults
            batchData={batchData}
            csvUrl={activeJobId ? apiClient.getBatchCsvUrl(activeJobId) : "#"}
            issuesCsvUrl={activeJobId ? apiClient.getBatchIssuesCsvUrl(activeJobId) : undefined}
          />
        )}
      </main>
    </div>
  );
}
