"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Globe,
  FileText,
  ListFilter,
  Sun,
  Moon,
  Laptop,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  CheckCircle2,
  AlertTriangle,
  LogOut,
  Target,
} from "lucide-react";
import AuditForm from "@/components/AuditForm";
import AuditResults from "@/components/AuditResults";
import BatchAuditResults from "@/components/BatchAuditResults";
import { apiClient, type AuditResponse, type BatchJobResponse } from "@/lib/api";
import {
  ChilizBrandBlock,
  ChilizTile,
  Segmented,
  Tooltip,
  ViewHeader,
  Card,
  Button,
} from "@/components/ui";
import { useTheme } from "@/components/theme-provider";

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
      <Globe
        className={`size-[18px] shrink-0 ${
          active ? "text-accent" : "text-nav-ink-2 group-hover:text-nav-ink"
        }`}
      />
    ),
  },
  {
    id: "text",
    label: "Paste Text",
    moduleNumber: "Module 2",
    description: "Draft & raw content evaluation",
    icon: (active) => (
      <FileText
        className={`size-[18px] shrink-0 ${
          active ? "text-accent" : "text-nav-ink-2 group-hover:text-nav-ink"
        }`}
      />
    ),
  },
  {
    id: "batch",
    label: "Batch Audit",
    moduleNumber: "Module 3",
    description: "Bulk audit up to 20 URLs",
    icon: (active) => (
      <ListFilter
        className={`size-[18px] shrink-0 ${
          active ? "text-accent" : "text-nav-ink-2 group-hover:text-nav-ink"
        }`}
      />
    ),
  },
];

export default function Home() {
  const { theme, setTheme } = useTheme();
  const [activeModule, setActiveModule] = useState<ModuleId>("url");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

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
  const fiveSecondTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (fiveSecondTimerRef.current) clearTimeout(fiveSecondTimerRef.current);
      if (abortControllerRef.current) abortControllerRef.current.abort();
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
    if (!fiveSecondTimerRef.current) {
      fiveSecondTimerRef.current = setTimeout(() => {
        setServerStatus((prev) => (prev === "checking" ? "waking_up" : prev));
      }, 5000);
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, 15000);

    try {
      const data = await apiClient.getVersion(controller.signal);
      clearTimeout(timeoutId);

      if (fiveSecondTimerRef.current) {
        clearTimeout(fiveSecondTimerRef.current);
        fiveSecondTimerRef.current = null;
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
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
      clearTimeout(timeoutId);
      const elapsed = Date.now() - wakeUpStartRef.current;
      if (elapsed >= 180000) {
        if (fiveSecondTimerRef.current) {
          clearTimeout(fiveSecondTimerRef.current);
          fiveSecondTimerRef.current = null;
        }
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        setServerStatus("unresponsive");
      } else {
        setServerStatus("waking_up");
        if (!pollIntervalRef.current) {
          pollIntervalRef.current = setInterval(() => {
            checkServerAndAuth();
          }, 5000);
        }
      }
    }
  }, []);

  const handleRetryServer = () => {
    wakeUpStartRef.current = Date.now();
    setServerStatus("checking");
    if (fiveSecondTimerRef.current) {
      clearTimeout(fiveSecondTimerRef.current);
      fiveSecondTimerRef.current = null;
    }
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
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
      // Ignore
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
      <div className="min-h-screen bg-plane flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-hairline border-t-accent rounded-full animate-spin" />
      </div>
    );
  }

  // 2. Waking up screen
  if (serverStatus === "waking_up") {
    return (
      <div className="min-h-screen bg-plane flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md text-center">
          <div className="flex justify-center mb-4">
            <ChilizTile className="size-12" />
          </div>
          <h1 className="text-2xl font-display font-bold tracking-tight text-ink mb-6">
            Socios · Chiliz
          </h1>
          <Card elevated className="p-8 text-center space-y-4">
            <div className="w-10 h-10 border-2 border-hairline border-t-accent rounded-full animate-spin mx-auto mb-2" />
            <h2 className="text-base font-semibold text-ink">
              Waking up the server… this can take up to a minute.
            </h2>
            <p className="text-xs text-ink-3 leading-relaxed max-w-xs mx-auto">
              Render free tier sleeps when inactive. Reconnecting automatically…
            </p>
          </Card>
        </div>
      </div>
    );
  }

  // 3. Unresponsive screen
  if (serverStatus === "unresponsive") {
    return (
      <div className="min-h-screen bg-plane flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md text-center">
          <div className="flex justify-center mb-4">
            <ChilizTile className="size-12" />
          </div>
          <h1 className="text-2xl font-display font-bold tracking-tight text-ink mb-6">
            Socios · Chiliz
          </h1>
          <Card elevated className="p-8 text-center space-y-4">
            <div className="flex justify-center">
              <AlertTriangle className="size-10 text-critical" />
            </div>
            <h2 className="text-base font-semibold text-ink">
              Server Unresponsive
            </h2>
            <p className="text-xs text-ink-3 max-w-xs mx-auto">
              The server is not responding. Please try again in a few minutes.
            </p>
            <Button
              variant="primary"
              onClick={handleRetryServer}
              className="w-full"
            >
              Retry
            </Button>
          </Card>
        </div>
      </div>
    );
  }

  // 4. Access Code Screen
  if (accessRequired && !isAuthenticated) {
    return (
      <div className="min-h-screen bg-plane flex flex-col items-center justify-center p-4 sm:p-6">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <div className="flex justify-center mb-4">
              <ChilizTile className="size-12" />
            </div>
            <h1 className="text-2xl font-display font-bold tracking-tight text-ink">
              Socios · Chiliz
            </h1>
            <p className="text-xs font-semibold tracking-wider uppercase text-brand-lilac mt-1">
              GEO Auditor — Private Access
            </p>
          </div>

          <Card elevated className="p-6 sm:p-8">
            <form onSubmit={handleAuthSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="access-code"
                  className="block text-micro font-semibold uppercase tracking-wider text-ink-2 mb-2"
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
                  className="input-field"
                />
                {authError && (
                  <div className="mt-3 p-3 rounded-control bg-critical-soft border border-critical/30 text-critical text-xs flex items-center gap-2">
                    <AlertTriangle className="size-4 shrink-0" />
                    <span>{authError}</span>
                  </div>
                )}
              </div>

              <Button
                type="submit"
                variant="primary"
                disabled={isSubmittingAuth || !accessCodeInput.trim()}
                className="w-full"
              >
                {isSubmittingAuth ? "Checking access..." : "Enter Dashboard"}
              </Button>
            </form>

            <div className="mt-6 pt-4 border-t border-hairline flex items-center justify-between text-micro text-ink-3">
              <span>Restricted access for authorized personnel</span>
              <span className="flex items-center gap-1.5 font-medium text-good">
                <span className="size-1.5 rounded-full bg-good" />
                Protected
              </span>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-plane flex flex-col">
      {/* Mobile Drawer Backdrop */}
      {mobileSidebarOpen && (
        <div
          onClick={() => setMobileSidebarOpen(false)}
          className="fixed inset-0 z-50 bg-scrim backdrop-blur-xs transition-opacity md:hidden"
        />
      )}

      {/* Left Sidebar (Dark Side Menu) */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 bg-nav-bg border-r border-nav-line flex flex-col justify-between transition-all duration-300 ease-in-out md:translate-x-0 ${
          sidebarCollapsed ? "w-18" : "w-64"
        } ${
          mobileSidebarOpen
            ? "translate-x-0 shadow-pop"
            : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="flex flex-col flex-1 min-h-0">
          {/* Brand Block */}
          <ChilizBrandBlock
            collapsed={sidebarCollapsed}
            subtitle="GEO AUDITOR"
          />

          {/* Navigation Items */}
          <div className="flex-1 overflow-y-auto px-3 py-4 space-y-4">
            <div>
              {!sidebarCollapsed ? (
                <div className="px-3 pb-2 text-micro font-bold tracking-[0.8px] text-nav-ink-3 uppercase select-none">
                  MAIN
                </div>
              ) : (
                <div className="h-4" />
              )}

              <nav className="space-y-1">
                {MODULE_NAV_ITEMS.map((item) => {
                  const isActive = activeModule === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => handleNavSelect(item.id)}
                      title={sidebarCollapsed ? `${item.moduleNumber}: ${item.label}` : undefined}
                      className={`w-full group relative text-left rounded-control transition-all cursor-pointer flex items-center select-none ${
                        sidebarCollapsed
                          ? "h-10 justify-center px-0"
                          : "h-10 px-3 gap-3"
                      } ${
                        isActive
                          ? "bg-nav-active font-semibold text-nav-active-ink"
                          : "text-nav-ink-2 hover:bg-nav-hover hover:text-nav-ink"
                      }`}
                    >
                      {/* Active Indicator Bar */}
                      {isActive && (
                        <span
                          className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-brand"
                          aria-hidden="true"
                        />
                      )}

                      <div className="shrink-0">{item.icon(isActive)}</div>

                      {!sidebarCollapsed && (
                        <div className="flex-1 min-w-0 flex items-center justify-between gap-1.5">
                          <span className="text-sm truncate">
                            {item.label}
                          </span>
                        </div>
                      )}
                    </button>
                  );
                })}
              </nav>
            </div>
          </div>
        </div>

        {/* Sidebar Footer: System Status & Collapse Toggle */}
        <div className="p-3 border-t border-nav-line bg-nav-hover/30 shrink-0 space-y-2">
          {!sidebarCollapsed ? (
            <>
              <div className="flex items-center justify-between px-2 py-1 text-xs">
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-good animate-pulse" />
                  <span className="font-medium text-nav-ink-2 text-micro">System</span>
                </div>
                <span className="text-[10px] font-mono text-good font-semibold bg-good-soft/20 border border-good/30 px-1.5 py-0.5 rounded">
                  ONLINE
                </span>
              </div>
              <div className="px-2 pt-1 flex items-center justify-between text-micro text-nav-ink-3 border-t border-nav-line">
                <span>{version}</span>
                {accessRequired && (
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="text-nav-ink-3 hover:text-accent font-medium transition-colors cursor-pointer flex items-center gap-1"
                  >
                    <LogOut className="size-3" />
                    <span>Log out</span>
                  </button>
                )}
              </div>
              <p className="px-2 text-[10px] text-nav-ink-3 pt-0.5">
                Built by{" "}
                <a
                  href="https://www.linkedin.com/in/carlos-cano-fernandez-seo-aso-manager/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-nav-ink-2 hover:text-nav-ink underline"
                >
                  Carlos Cano Fernandez
                </a>
              </p>
            </>
          ) : (
            <div className="flex justify-center py-1">
              <span className="size-2 rounded-full bg-good" title="System Online" />
            </div>
          )}

          {/* Desktop Collapse Toggle */}
          <button
            type="button"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className={`w-full hidden md:flex items-center rounded-control py-2 text-micro font-medium text-nav-ink-3 hover:text-nav-ink hover:bg-nav-hover transition-colors cursor-pointer select-none ${
              sidebarCollapsed ? "justify-center px-0" : "justify-between px-2.5"
            }`}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {!sidebarCollapsed && <span>Collapse</span>}
            {sidebarCollapsed ? (
              <PanelLeftOpen className="size-4 shrink-0" />
            ) : (
              <PanelLeftClose className="size-4 shrink-0" />
            )}
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div
        className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
          sidebarCollapsed ? "md:pl-18" : "md:pl-64"
        }`}
      >
        {/* Sticky Translucent Top Bar */}
        <header className="sticky top-0 z-30 border-b border-hairline bg-surface/75 backdrop-blur-md no-print">
          <div className="mx-auto w-full max-w-[1600px] min-h-16 px-4 py-3 sm:px-6 lg:px-8 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                onClick={() => setMobileSidebarOpen(true)}
                className="p-1.5 -ml-1 rounded-control text-ink-2 hover:text-ink hover:bg-surface-2 md:hidden cursor-pointer"
                aria-label="Open navigation menu"
              >
                <Menu className="size-5" />
              </button>

              <div className="flex items-center gap-2 truncate">
                <span className="font-semibold text-sm sm:text-[0.9375rem] text-ink truncate">
                  {currentNav.label}
                </span>
                <span className="text-hairline-strong hidden sm:inline" aria-hidden="true">
                  /
                </span>
                <span className="text-xs text-ink-2 hidden sm:inline truncate">
                  {currentNav.description}
                </span>
              </div>
            </div>

            {/* Right Status Badges & Theme Switcher */}
            <div className="flex items-center gap-2 shrink-0">
              {/* Theme Switcher */}
              <Segmented
                size="sm"
                value={theme}
                onChange={(val) => setTheme(val as "light" | "dark" | "system")}
                options={[
                  {
                    value: "light",
                    label: <span className="sr-only">Light</span>,
                    icon: <Sun className="size-3.5" />,
                  },
                  {
                    value: "dark",
                    label: <span className="sr-only">Dark</span>,
                    icon: <Moon className="size-3.5" />,
                  },
                  {
                    value: "system",
                    label: <span className="sr-only">System</span>,
                    icon: <Laptop className="size-3.5" />,
                  },
                ]}
                className="hidden sm:inline-flex"
              />

              {/* AI Connected Badge */}
              <Tooltip content={aiEnabled ? "AI Connected (AI model & fixes enabled)" : "AI Disconnected (No API key)"}>
                <div
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-micro font-medium border ${
                    aiEnabled
                      ? "border-good/30 bg-good-soft text-good"
                      : "border-hairline bg-surface-2 text-ink-3"
                  }`}
                >
                  <span className={`size-1.5 rounded-full ${aiEnabled ? "bg-good animate-pulse" : "bg-ink-3"}`} />
                  <span className="hidden sm:inline">AI Connected</span>
                  <span className="sm:hidden">AI</span>
                </div>
              </Tooltip>

              {/* Google Data Badge */}
              <Tooltip content={serpEnabled ? "Google Data Connected (Live SERP/PAA enabled)" : "Google Data Disabled"}>
                <div
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-micro font-medium border ${
                    serpEnabled
                      ? "border-good/30 bg-good-soft text-good"
                      : "border-hairline bg-surface-2 text-ink-3"
                  }`}
                >
                  <span className={`size-1.5 rounded-full ${serpEnabled ? "bg-good animate-pulse" : "bg-ink-3"}`} />
                  <span className="hidden sm:inline">Google data</span>
                  <span className="sm:hidden">Google</span>
                </div>
              </Tooltip>

              {/* Ahrefs Badge */}
              <Tooltip content={ahrefsEnabled ? "Ahrefs API Connected (Off-page metrics enabled)" : "Ahrefs API Disabled"}>
                <div
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-micro font-medium border ${
                    ahrefsEnabled
                      ? "border-good/30 bg-good-soft text-good"
                      : "border-hairline bg-surface-2 text-ink-3"
                  }`}
                >
                  <span className={`size-1.5 rounded-full ${ahrefsEnabled ? "bg-good animate-pulse" : "bg-ink-3"}`} />
                  <span>Ahrefs</span>
                </div>
              </Tooltip>
            </div>
          </div>
        </header>

        {/* Page Content Body */}
        <main className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto w-full">
          {/* Page Banner / Header */}
          <div className="no-print">
            <ViewHeader
              title={
                activeModule === "url"
                  ? "Audit Page URL"
                  : activeModule === "text"
                  ? "Audit Raw Content"
                  : "Batch Audit Multiple URLs"
              }
              description={
                activeModule === "url"
                  ? "Evaluate single page citability potential across leading AI engines (ChatGPT, Perplexity, Gemini, Claude)."
                  : activeModule === "text"
                  ? "Paste draft content or article text before publishing to optimize citations."
                  : "Audit up to 20 URLs at once to detect site-wide and topic-level issues."
              }
            />
          </div>

          {/* Audit Input Card */}
          <Card elevated className="p-6 no-print">
            <AuditForm
              key={formKey}
              initialUrl={formUrl}
              initialMode={formMode}
              onSubmit={handleAudit}
              onBatchSubmit={handleBatchAudit}
              isLoading={isLoading}
              batchProgress={batchProgress}
            />
          </Card>

          {/* Error Banner */}
          {error && (
            <div className="p-4 bg-critical-soft border border-critical/30 rounded-card flex items-center gap-3 text-critical text-sm shadow-sm">
              <AlertTriangle className="size-5 shrink-0" />
              <p className="font-medium">{error}</p>
            </div>
          )}

          {/* Loading Card */}
          {isLoading && !batchData && (
            <Card elevated className="p-12 text-center space-y-4">
              <div className="w-10 h-10 border-2 border-hairline border-t-accent rounded-full animate-spin mx-auto" />
              <h3 className="text-lg font-bold text-ink">Analyzing Content...</h3>
              <p className="text-xs text-ink-3">
                Running comprehensive citability audit across 11 dimensions...
              </p>
            </Card>
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
            <Card elevated className="p-8 sm:p-12 text-center space-y-6">
              <div className="size-16 mx-auto rounded-card bg-accent-soft text-accent flex items-center justify-center text-3xl font-bold shadow-xs">
                <Target className="size-8" />
              </div>
              <div className="max-w-md mx-auto space-y-2">
                <h3 className="text-lg font-bold text-ink">
                  Ready to Audit Content
                </h3>
                <p className="text-xs text-ink-3 leading-relaxed">
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
                  <div key={idx} className="p-3.5 bg-surface-2 rounded-control border border-hairline space-y-0.5">
                    <p className="text-xs font-semibold text-ink flex items-center gap-1.5">
                      <CheckCircle2 className="size-3.5 text-accent" /> {item.title}
                    </p>
                    <p className="text-micro text-ink-3 pl-5">{item.desc}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </main>
      </div>
    </div>
  );
}
