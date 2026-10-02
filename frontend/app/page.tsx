"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import AuditForm from "@/components/AuditForm";
import AuditResults from "@/components/AuditResults";
import BatchAuditResults from "@/components/BatchAuditResults";
import { apiClient, type AuditResponse, type BatchJobResponse } from "@/lib/api";

type ModuleId = "url" | "text" | "batch";

const MODULE_NAV_ITEMS: {
  id: ModuleId;
  label: string;
  moduleNumber: string;
  description: string;
  icon: (active: boolean) => React.ReactNode;
}[] = [
  {
    id: "url",
    label: "URL Audit",
    moduleNumber: "Module 1",
    description: "Single page citability analysis",
    icon: (active) => (
      <svg
        className={`w-5 h-5 shrink-0 ${active ? "text-red-600" : "text-slate-400 group-hover:text-slate-600"}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
      </svg>
    ),
  },
  {
    id: "text",
    label: "Paste Text",
    moduleNumber: "Module 2",
    description: "Draft & raw content evaluation",
    icon: (active) => (
      <svg
        className={`w-5 h-5 shrink-0 ${active ? "text-red-600" : "text-slate-400 group-hover:text-slate-600"}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    id: "batch",
    label: "Batch Audit",
    moduleNumber: "Module 3",
    description: "Bulk audit up to 20 URLs",
    icon: (active) => (
      <svg
        className={`w-5 h-5 shrink-0 ${active ? "text-red-600" : "text-slate-400 group-hover:text-slate-600"}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
];

export default function Home() {
  const [activeModule, setActiveModule] = useState<ModuleId>("url");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<AuditResponse | null>(null);
  const [batchData, setBatchData] = useState<BatchJobResponse | null>(null);
  const [batchProgress, setBatchProgress] = useState<{ completed: number; total: number } | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState("v2.3");
  const [aiEnabled, setAiEnabled] = useState(false);
  const [serpEnabled, setSerpEnabled] = useState(false);
  const [ahrefsEnabled, setAhrefsEnabled] = useState(false);

  const [accessRequired, setAccessRequired] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(true);
  const [serverStatus, setServerStatus] = useState<"checking" | "waking_up" | "unresponsive" | "ready">("checking");
  const [accessCodeInput, setAccessCodeInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);

  const [formUrl, setFormUrl] = useState("");
  const [formMode, setFormMode] = useState<ModuleId>("url");
  const [formKey, setFormKey] = useState(0);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const wakeUpStartRef = useRef<number>(Date.now());
  const wakeUpTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (wakeUpTimerRef.current) clearInterval(wakeUpTimerRef.current);
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

  const checkServerAndAuth = useCallback(async () => {
    try {
      const data = await apiClient.getVersion();
      if (wakeUpTimerRef.current) {
        clearInterval(wakeUpTimerRef.current);
        wakeUpTimerRef.current = null;
      }
      setServerStatus("ready");

      if (data?.version) setVersion(data.version);
      if (data?.ai_enabled !== undefined) setAiEnabled(Boolean(data.ai_enabled));
      if (data?.serp_enabled !== undefined) setSerpEnabled(Boolean(data.serp_enabled));
      if (data?.ahrefs_enabled !== undefined) setAhrefsEnabled(Boolean(data.ahrefs_enabled));

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
    } catch {
      const elapsed = Date.now() - wakeUpStartRef.current;
      if (elapsed >= 180000) {
        if (wakeUpTimerRef.current) {
          clearInterval(wakeUpTimerRef.current);
          wakeUpTimerRef.current = null;
        }
        setServerStatus("unresponsive");
      } else {
        setServerStatus("waking_up");
        if (!wakeUpTimerRef.current) {
          wakeUpTimerRef.current = setInterval(() => {
            checkServerAndAuth();
          }, 5000);
        }
      }
    }
  }, []);

  const handleRetryServer = () => {
    wakeUpStartRef.current = Date.now();
    setServerStatus("waking_up");
    if (wakeUpTimerRef.current) {
      clearInterval(wakeUpTimerRef.current);
      wakeUpTimerRef.current = null;
    }
    checkServerAndAuth();
  };

  useEffect(() => {
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

    checkServerAndAuth();
  }, [checkServerAndAuth]);

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

  const handleAnalyzeWithAI = (targetUrl: string) => {
    setFormUrl(targetUrl);
    setFormMode("url");
    setActiveModule("url");
    setFormKey((prev) => prev + 1);
    handleAudit(targetUrl, null, undefined);
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

      await poll();
      pollIntervalRef.current = setInterval(poll, 5000);
    } catch (err) {
      setIsLoading(false);
      setBatchProgress(null);
      setError(err instanceof Error ? err.message : "Failed to initiate batch audit");
    }
  };

  const handleNavSelect = (id: ModuleId) => {
    setActiveModule(id);
    setFormMode(id);
    setMobileSidebarOpen(false);
  };

  const currentNav = MODULE_NAV_ITEMS.find((item) => item.id === activeModule) || MODULE_NAV_ITEMS[0];

  // 1. Loading screen
  if (serverStatus === "checking") {
    return (
      <div className="min-h-screen bg-[#f1f5f9] flex items-center justify-center">
        <div className="w-10 h-10 border-3 border-slate-200 border-t-red-600 rounded-full animate-spin" />
      </div>
    );
  }

  // 2. Waking up screen
  if (serverStatus === "waking_up") {
    return (
      <div className="min-h-screen bg-[#f1f5f9] flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-red-600 text-white font-bold text-xl shadow-md shadow-red-600/25 mb-4">
            S
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 mb-6">
            Socios · Chiliz
          </h1>
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8 text-center space-y-4">
            <div className="w-10 h-10 border-3 border-slate-200 border-t-red-600 rounded-full animate-spin mx-auto mb-2" />
            <h2 className="text-base font-bold text-slate-900">
              Waking up the server…
            </h2>
            <p className="text-xs text-slate-500 leading-relaxed max-w-xs mx-auto">
              Render free tier sleeps when inactive. This can take up to a minute to start.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // 3. Unresponsive screen
  if (serverStatus === "unresponsive") {
    return (
      <div className="min-h-screen bg-[#f1f5f9] flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-red-600 text-white font-bold text-xl shadow-md shadow-red-600/25 mb-4">
            S
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 mb-6">
            Socios · Chiliz
          </h1>
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8 text-center space-y-4">
            <div className="text-3xl">⚠️</div>
            <h2 className="text-base font-bold text-slate-900">
              Server Unresponsive
            </h2>
            <p className="text-xs text-slate-500 max-w-xs mx-auto">
              The server is not responding. Please try again in a few minutes.
            </p>
            <button
              type="button"
              onClick={handleRetryServer}
              className="w-full py-2.5 px-4 rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium text-sm shadow-sm transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 4. Access Code Screen
  if (accessRequired && !isAuthenticated) {
    return (
      <div className="min-h-screen bg-[#f1f5f9] flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-red-600 text-white font-bold text-xl shadow-md shadow-red-600/25 mb-4">
              S
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              Socios · Chiliz
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              GEO Auditor — Private Access
            </p>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-8">
            <form onSubmit={handleAuthSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="access-code"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-2"
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
                  placeholder="Enter access code..."
                  autoFocus
                  disabled={isSubmittingAuth}
                  className="w-full px-4 py-2.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 text-sm focus:outline-none focus:bg-white focus:border-red-500 focus:ring-2 focus:ring-red-500/20 transition-all disabled:opacity-60"
                />
                {authError && (
                  <div className="mt-3 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center gap-2">
                    <span>⚠️</span>
                    <span>{authError}</span>
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={isSubmittingAuth || !accessCodeInput.trim()}
                className="w-full py-2.5 px-4 rounded-lg bg-red-600 hover:bg-red-500 active:bg-red-700 text-white font-medium text-sm shadow-sm transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                {isSubmittingAuth ? "Checking access..." : "Enter Dashboard"}
              </button>
            </form>

            <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
              <span>Restricted access for authorized personnel</span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                Protected
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f1f5f9] flex flex-col">
      {/* Mobile Drawer Backdrop */}
      {mobileSidebarOpen && (
        <div
          onClick={() => setMobileSidebarOpen(false)}
          className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs transition-opacity lg:hidden"
        />
      )}

      {/* Left Sidebar (Desktop Fixed + Mobile Slide-over Drawer) */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-slate-200 flex flex-col justify-between transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          mobileSidebarOpen ? "translate-x-0 shadow-2xl" : "-translate-x-full"
        }`}
      >
        <div className="flex flex-col flex-1 min-h-0">
          {/* Brand Block */}
          <div className="h-16 px-6 border-b border-slate-200 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center font-bold text-white text-base shadow-sm shadow-red-600/30">
                S
              </div>
              <div className="flex flex-col">
                <span className="font-bold tracking-tight text-slate-900 text-sm leading-tight">
                  Socios · Chiliz
                </span>
                <span className="text-[11px] text-slate-500 font-medium leading-tight">
                  GEO Auditor
                </span>
              </div>
            </div>

            {/* Mobile close button */}
            <button
              onClick={() => setMobileSidebarOpen(false)}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 lg:hidden cursor-pointer"
              title="Close navigation"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Navigation Items */}
          <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
            <div>
              <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Audit Modules
              </div>
              <nav className="space-y-1.5">
                {MODULE_NAV_ITEMS.map((item) => {
                  const isActive = activeModule === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => handleNavSelect(item.id)}
                      className={`w-full group text-left px-3.5 py-3 rounded-xl transition-all cursor-pointer flex items-center gap-3.5 ${
                        isActive
                          ? "bg-red-50/70 border border-red-200 text-red-700 shadow-xs"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-transparent"
                      }`}
                    >
                      <div className="shrink-0">{item.icon(isActive)}</div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1.5">
                          <span
                            className={`text-xs font-semibold truncate ${
                              isActive ? "text-slate-900 font-bold" : "text-slate-700 group-hover:text-slate-900"
                            }`}
                          >
                            {item.label}
                          </span>
                        </div>
                        <p
                          className={`text-[11px] truncate ${
                            isActive ? "text-red-700/80 font-medium" : "text-slate-400"
                          }`}
                        >
                          {item.description}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </nav>
            </div>
          </div>
        </div>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-slate-200 bg-slate-50/50 space-y-2">
          <div className="flex items-center justify-between px-2 py-1 text-xs">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="font-medium text-slate-700 text-[11px]">System Status</span>
            </div>
            <span className="text-[10px] font-mono text-emerald-700 font-semibold bg-emerald-50 border border-emerald-200 px-1.5 py-0.2 rounded">
              ONLINE
            </span>
          </div>
          <div className="px-2 pt-1 flex items-center justify-between text-[11px] text-slate-500 border-t border-slate-200/60">
            <span>{version}</span>
            {accessRequired && (
              <button
                type="button"
                onClick={handleLogout}
                className="text-slate-500 hover:text-red-600 font-medium transition-colors cursor-pointer"
              >
                Log out
              </button>
            )}
          </div>
          <p className="px-2 text-[10px] text-slate-400 pt-0.5">
            Built by{" "}
            <a
              href="https://www.linkedin.com/in/carlos-cano-fernandez-seo-aso-manager/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-500 hover:text-slate-700 underline"
            >
              Carlos Cano Fernandez
            </a>
          </p>
        </div>
      </aside>

      {/* Main Content Area (Offset by sidebar width on desktop) */}
      <div className="flex-1 flex flex-col min-w-0 lg:pl-72">
        {/* Top Header Bar */}
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-md shadow-xs no-print">
          <div className="px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                onClick={() => setMobileSidebarOpen(true)}
                className="p-2 -ml-2 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 lg:hidden cursor-pointer"
                aria-label="Open sidebar"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>

              <div className="flex items-center gap-2 truncate">
                <span className="font-semibold tracking-tight text-slate-900 text-sm sm:text-base truncate">
                  {currentNav.label}
                </span>
                <span className="text-slate-400 hidden sm:inline">/</span>
                <span className="text-slate-500 text-xs hidden sm:inline">
                  {currentNav.description}
                </span>
              </div>
            </div>

            {/* Right Status Badges */}
            <div className="flex items-center gap-2 shrink-0">
              {/* AI Connected Badge */}
              <div
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border shadow-2xs ${
                  aiEnabled
                    ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                    : "bg-slate-100 border-slate-200 text-slate-500"
                }`}
                title={aiEnabled ? "AI Connected (Claude & fixes enabled)" : "AI Disconnected (No API key)"}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${aiEnabled ? "bg-emerald-500 animate-pulse" : "bg-slate-400"}`} />
                <span className="hidden xs:inline">AI Connected</span>
                <span className="xs:hidden">AI</span>
              </div>

              {/* Google Data Badge */}
              <div
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border shadow-2xs ${
                  serpEnabled
                    ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                    : "bg-slate-100 border-slate-200 text-slate-500"
                }`}
                title={serpEnabled ? "Google Data Connected (Live SERP/PAA enabled)" : "Google Data Disabled"}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${serpEnabled ? "bg-emerald-500 animate-pulse" : "bg-slate-400"}`} />
                <span className="hidden xs:inline">Google data</span>
                <span className="xs:hidden">Google</span>
              </div>

              {/* Ahrefs Badge */}
              <div
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border shadow-2xs ${
                  ahrefsEnabled
                    ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                    : "bg-slate-100 border-slate-200 text-slate-500"
                }`}
                title={ahrefsEnabled ? "Ahrefs API Connected (Off-page metrics enabled)" : "Ahrefs API Disabled"}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${ahrefsEnabled ? "bg-emerald-500 animate-pulse" : "bg-slate-400"}`} />
                <span>Ahrefs</span>
              </div>
            </div>
          </div>
        </header>

        {/* Page Content Body */}
        <main className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto w-full">
          {/* Audit Input Card */}
          <div className="glass-card p-6 no-print">
            <div className="mb-4">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                {activeModule === "url"
                  ? "Audit Page URL"
                  : activeModule === "text"
                  ? "Audit Raw Content"
                  : "Batch Audit Multiple URLs"}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {activeModule === "url"
                  ? "Evaluate single page citability potential across leading AI engines."
                  : activeModule === "text"
                  ? "Paste draft content or article text before publishing."
                  : "Audit up to 20 URLs at once to detect site-wide and topic-level issues."}
              </p>
            </div>

            <AuditForm
              key={formKey}
              initialUrl={formUrl}
              initialMode={formMode}
              onModeChange={(newMode) => {
                setActiveModule(newMode);
                setFormMode(newMode);
              }}
              onSubmit={handleAudit}
              onBatchSubmit={handleBatchAudit}
              isLoading={isLoading}
              batchProgress={batchProgress}
            />
          </div>

          {/* Error Banner */}
          {error && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-2xl flex items-center gap-3 text-red-700 text-sm shadow-sm">
              <span className="text-xl">⚠️</span>
              <p className="font-medium">{error}</p>
            </div>
          )}

          {/* Loading Card */}
          {isLoading && !batchData && (
            <div className="glass-card p-12 text-center space-y-4">
              <div className="w-10 h-10 border-3 border-slate-200 border-t-red-600 rounded-full animate-spin mx-auto" />
              <h3 className="text-lg font-bold text-slate-900">Analyzing Content...</h3>
              <p className="text-xs text-slate-500">
                Running comprehensive citability audit across 11 dimensions...
              </p>
            </div>
          )}

          {/* Individual Audit Results */}
          {results && !isLoading && <AuditResults results={results} />}

          {/* Batch Audit Results */}
          {batchData && (
            <BatchAuditResults
              batchData={batchData}
              csvUrl={activeJobId ? apiClient.getBatchCsvUrl(activeJobId) : "#"}
              issuesCsvUrl={activeJobId ? apiClient.getBatchIssuesCsvUrl(activeJobId) : undefined}
              aiEnabled={aiEnabled}
              onAnalyzeWithAI={handleAnalyzeWithAI}
              onRetryFailed={handleBatchAudit}
            />
          )}

          {/* Ready to Audit State */}
          {!results && !batchData && !isLoading && (
            <div className="glass-card p-8 sm:p-12 text-center space-y-6">
              <div className="w-16 h-16 mx-auto rounded-2xl bg-red-50 text-red-600 flex items-center justify-center text-3xl font-bold shadow-2xs">
                🎯
              </div>
              <div className="max-w-md mx-auto space-y-2">
                <h3 className="text-lg font-bold text-slate-900">
                  Ready to Audit Content
                </h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Enter a target URL or paste draft text above to evaluate how AI search engines (ChatGPT, Perplexity, Gemini, Claude) perceive, parse, and cite your content.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl mx-auto text-left pt-2">
                {[
                  { title: "AEO Answer Optimization", desc: "First 60 words & direct answers" },
                  { title: "Entity & Schema Graph", desc: "JSON-LD, Authorship & Publishers" },
                  { title: "Evidence & Facts Density", desc: "Citations, numbers & verifiable data" },
                  { title: "Off-page Ahrefs Signals", desc: "Backlinks & domain authority check" },
                ].map((item, idx) => (
                  <div key={idx} className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/80 space-y-0.5">
                    <p className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                      <span className="text-red-600">✓</span> {item.title}
                    </p>
                    <p className="text-[11px] text-slate-500 pl-4">{item.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
