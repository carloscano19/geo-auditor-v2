/**
 * GEO-AUDITOR AI - API Client
 * 
 * Centralized API client for communicating with the FastAPI backend.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface AuditRequest {
    url?: string;
    content_text?: string;
    target_query?: string;
}

export interface ScoreBreakdown {
    name: string;
    raw_score: number;
    weight: number;
    weighted_score: number;
    explanation: string;
    recommendations: string[];
}

export interface DetectorResult {
    dimension: string;
    score: number;
    weight: number;
    contribution: number;
    breakdown: ScoreBreakdown[];
    errors: string[];
    debug_info?: Record<string, unknown>;
}

export interface DimensionScore {
    name: string;
    score: number;
    weight: number;
    contribution: number;
    status: 'green' | 'yellow' | 'red';
}

export interface FailingSubmetric {
    name: string;
    score: number;
    recommendation?: string;
}

export interface AIContext {
    url?: string;
    title?: string;
    h1?: string;
    language: string;
    content_type: string;
    main_text: string;
    first_paragraph?: string;
    existing_json_ld: Record<string, unknown>[];
    detected_author?: string;
    detected_date_published?: string;
    detected_date_modified?: string;
    detected_publisher?: string;
    publisher_inferred_from_domain?: boolean;
    detected_image_url?: string;
    target_query?: string;
    failing_submetrics: FailingSubmetric[];
}

export interface LeadParagraphFix {
    original: string;
    suggested: string;
    rationale: string;
}

export interface AIFixesResponse {
    json_ld: Record<string, unknown>;
    lead_paragraph: LeadParagraphFix;
    warnings: string[];
}

export interface PlanQuestion {
    question: string;
    draft_answer: string;
    answer_source: 'page' | 'needs_info';
    origin?: 'google_paa' | 'ai';
}

export interface PlanOutlineItem {
    h2: string;
    purpose: string;
    status: 'existing' | 'new';
}

export interface PlanTable {
    title: string;
    headers?: string[] | null;
    rows?: string[][] | null;
    table_idea?: string | null;
}

export interface PlanDataOpportunity {
    suggestion: string;
    source_type: string;
}

export interface PlanNewParagraph {
    target_issue: string;
    suggested_text: string;
    placement: string;
}

export interface PlanInconsistency {
    issue: string;
    values: string[];
    suggestion: string;
}

export interface PlanSourceToCite {
    url: string;
    title: string;
    domain: string;
    found_in: 'AI Overview' | 'Organic top 10';
    why: string;
}

export interface AIPlanResponse {
    questions_to_answer: PlanQuestion[];
    suggested_h2_structure: PlanOutlineItem[];
    suggested_table?: PlanTable | null;
    data_opportunities: PlanDataOpportunity[];
    paragraphs_to_add: PlanNewParagraph[];
    inconsistencies: PlanInconsistency[];
    sources_to_cite?: PlanSourceToCite[];
    combined_schema: Record<string, unknown>;
    warnings: string[];
    serp_query?: string | null;
    serp_market?: string | null;
    serp_used?: boolean;
    serp_paa_found?: number;
}

export interface AIPlanRequest {
    ai_context: AIContext;
    target_query?: string;
    query?: string;
}

export interface AhrefsOffpageResponse {
    domain_rating: number | null;
    url_rating: number | null;
    referring_domains: number | null;
    backlinks: number | null;
    referring_domains_all_time: number | null;
    organic_keywords: number | null;
    top3_keywords: number | null;
    organic_traffic: number | null;
    checked_at: string;
    recommendations: string[];
}

export interface BriefExportRequest {
    audit_result: AuditResponse;
    ai_fixes?: AIFixesResponse | null;
    ai_plan?: AIPlanResponse | null;
    ahrefs_offpage?: AhrefsOffpageResponse | null;
}

export interface AuditResponse {
    url: string;
    total_score: number;
    dimensions: DimensionScore[];
    scoring_version: string;
    language?: string;
    content_type?: string;
    analysis_time_ms: number;
    analyzed_at: string;
    recommendations: string[];
    score_capped?: boolean;
    cap_reason?: string;
    detector_results: DetectorResult[];
    ai_context?: AIContext;
}

export interface HealthStatus {
    status: string;
    version: string;
    timestamp: string;
}

export interface BatchAuditRequest {
    urls: string[];
    target_query?: string;
}

export interface BatchItemResult {
    url: string;
    status: 'pending' | 'running' | 'done' | 'error';
    result?: AuditResponse;
    error?: string;
}

export interface RecommendationBreakdownItem {
    recommendation: string;
    page_count: number;
}

export interface TopicIssue {
    dimension: string;
    submetric: string;
    affected_count: number;
    affected_urls: string[];
    top_recommendation?: string;
    recommendation_breakdown?: RecommendationBreakdownItem[];
    impact: number;
    domain?: string;
    total_domain_pages?: number;
}

export interface BatchJobResponse {
    job_id: string;
    status: 'pending' | 'running' | 'done';
    total: number;
    completed: number;
    results: BatchItemResult[];
    issues_by_topic: TopicIssue[];
    site_wide_issues?: TopicIssue[];
    created_at: string;
    completed_at?: string | null;
}

export const DIMENSION_DISPLAY_NAMES: Record<string, string> = {
    technical_infrastructure: "Technical Infrastructure",
    metadata_schema: "Metadata & Schema",
    aeo_structure: "AEO Structure",
    evidence_density: "Evidence Density",
    eeat_authority: "E-E-A-T Authority",
    entity_identification: "Entity Identification",
    freshness: "Freshness & Currency",
    format_citability: "Formatting & Scannability",
    links_verifiability: "Links & Verifiability",
    passage_quality: "Passage Quality",
    query_match: "Query Match & Relevance",
};

export const CONTENT_TYPE_DISPLAY_NAMES: Record<string, string> = {
    news: "News",
    guide_blog: "Guide/Blog",
    review: "Review",
    product: "Product",
};

export function getDimensionDisplayName(dim: string): string {
    return DIMENSION_DISPLAY_NAMES[dim] || dim.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

export function getContentTypeDisplayName(ct: string): string {
    return CONTENT_TYPE_DISPLAY_NAMES[ct] || ct.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

export const SERVER_BUSY_MESSAGE = 'The server is waking up or busy. Please try again in a minute.';

class ApiClient {
    private baseUrl: string;

    constructor(baseUrl: string = API_BASE_URL) {
        this.baseUrl = baseUrl;
    }

    getStoredAccessCode(): string | null {
        if (typeof window !== 'undefined') {
            try {
                return localStorage.getItem('geo_auditor_access_code');
            } catch {
                return null;
            }
        }
        return null;
    }

    setStoredAccessCode(code: string): void {
        if (typeof window !== 'undefined') {
            try {
                localStorage.setItem('geo_auditor_access_code', code);
            } catch {
                // Ignore storage errors
            }
        }
    }

    clearStoredAccessCode(): void {
        if (typeof window !== 'undefined') {
            try {
                localStorage.removeItem('geo_auditor_access_code');
            } catch {
                // Ignore storage errors
            }
        }
    }

    private async parseResponse<T>(response: Response, defaultError: string): Promise<T> {
        if (response.status === 502 || response.status === 503 || response.status === 504) {
            throw new Error(SERVER_BUSY_MESSAGE);
        }

        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            throw new Error(SERVER_BUSY_MESSAGE);
        }

        let data: Record<string, unknown> = {};
        try {
            data = (await response.json()) as Record<string, unknown>;
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }

        if (!response.ok) {
            throw new Error((data?.detail as string) || defaultError);
        }

        return data as unknown as T;
    }

    private async fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
        const headers = new Headers(options.headers || {});
        const code = this.getStoredAccessCode();
        if (code) {
            headers.set('X-Access-Code', code);
        }
        let response: Response;
        try {
            response = await fetch(url, { ...options, headers });
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        if (response.status === 401) {
            this.clearStoredAccessCode();
            if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('geo_auditor_unauthorized'));
            }
        }
        return response;
    }

    /**
     * Check API health status (exempt from access code)
     */
    async health(): Promise<HealthStatus> {
        let response: Response;
        try {
            response = await fetch(`${this.baseUrl}/api/health`);
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        return this.parseResponse<HealthStatus>(response, 'API is not available');
    }

    /**
     * Check access code validity via POST /api/auth/check
     */
    async checkAuth(code: string): Promise<{ ok: boolean; error?: string }> {
        try {
            const response = await fetch(`${this.baseUrl}/api/auth/check`, {
                method: 'POST',
                headers: {
                    'X-Access-Code': code,
                },
            });
            if (response.status === 200) {
                return { ok: true };
            }
            if (response.status === 429) {
                const data = await response.json().catch(() => ({}));
                return { ok: false, error: data?.detail || 'Too many attempts, try again later' };
            }
            if (response.status === 502 || response.status === 503 || response.status === 504) {
                return { ok: false, error: SERVER_BUSY_MESSAGE };
            }
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                return { ok: false, error: SERVER_BUSY_MESSAGE };
            }
            const data = await response.json().catch(() => ({}));
            return { ok: false, error: data?.detail || 'Invalid access code' };
        } catch {
            return { ok: false, error: SERVER_BUSY_MESSAGE };
        }
    }

    /**
     * Run audit on a URL
     */
    async audit(request: AuditRequest): Promise<AuditResponse> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/audit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });
        return this.parseResponse<AuditResponse>(response, 'Audit failed');
    }

    /**
     * Start a batch audit
     */
    async startBatch(request: BatchAuditRequest): Promise<{ job_id: string }> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });
        return this.parseResponse<{ job_id: string }>(response, 'Batch audit initiation failed');
    }

    /**
     * Get batch job status
     */
    async getBatchStatus(jobId: string): Promise<BatchJobResponse> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/batch/${jobId}`);
        return this.parseResponse<BatchJobResponse>(response, 'Failed to get batch status');
    }

    /**
     * Download batch summary CSV using fetch with auth and trigger Blob download
     */
    async downloadBatchCsv(jobId: string): Promise<void> {
        let response: Response;
        try {
            response = await this.fetchWithAuth(`${this.baseUrl}/api/batch/${jobId}/csv`);
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        if (response.status === 502 || response.status === 503 || response.status === 504) {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        if (!response.ok) {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err?.detail || 'Failed to download batch CSV');
            }
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition');
        let filename = `geo_audit_batch_${jobId.slice(0, 8)}.csv`;
        if (disposition && disposition.includes('filename=')) {
            const match = disposition.match(/filename="?([^"]+)"?/);
            if (match && match[1]) filename = match[1];
        }
        const blobUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(blobUrl);
    }

    /**
     * Download batch aggregated issues CSV using fetch with auth and trigger Blob download
     */
    async downloadBatchIssuesCsv(jobId: string): Promise<void> {
        let response: Response;
        try {
            response = await this.fetchWithAuth(`${this.baseUrl}/api/batch/${jobId}/issues.csv`);
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        if (response.status === 502 || response.status === 503 || response.status === 504) {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        if (!response.ok) {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err?.detail || 'Failed to download issues CSV');
            }
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition');
        let filename = `geo_audit_issues_${jobId.slice(0, 8)}.csv`;
        if (disposition && disposition.includes('filename=')) {
            const match = disposition.match(/filename="?([^"]+)"?/);
            if (match && match[1]) filename = match[1];
        }
        const blobUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(blobUrl);
    }

    /**
     * Get batch CSV download URL (fallback reference)
     */
    getBatchCsvUrl(jobId: string): string {
        return `${this.baseUrl}/api/batch/${jobId}/csv`;
    }

    /**
     * Get batch issues CSV download URL (fallback reference)
     */
    getBatchIssuesCsvUrl(jobId: string): string {
        return `${this.baseUrl}/api/batch/${jobId}/issues.csv`;
    }

    /**
     * Get scoring weights configuration
     */
    async getScoringWeights(): Promise<Record<string, unknown>> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/scoring-weights`);
        return this.parseResponse<Record<string, unknown>>(response, 'Failed to fetch scoring weights');
    }

    /**
     * Get backend version (single source of truth, exempt from access code)
     */
    async getVersion(signal?: AbortSignal): Promise<{
        version: string;
        ai_enabled?: boolean;
        serp_enabled?: boolean;
        access_required?: boolean;
        ahrefs_enabled?: boolean;
    }> {
        let response: Response;
        try {
            response = await fetch(`${this.baseUrl}/api/version`, { signal });
        } catch {
            throw new Error(SERVER_BUSY_MESSAGE);
        }
        return this.parseResponse(response, 'Failed to fetch version');
    }

    /**
     * Generate AI suggested fixes for Schema.org and lead paragraph
     */
    async generateAIFixes(aiContext: AIContext): Promise<AIFixesResponse> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/ai/fixes`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ai_context: aiContext }),
        });
        return this.parseResponse<AIFixesResponse>(response, 'Failed to generate AI fixes');
    }

    /**
     * Generate comprehensive AI improvement plan
     */
    async generateAIPlan(aiContext: AIContext, query?: string): Promise<AIPlanResponse> {
        const bodyPayload: Record<string, unknown> = { ai_context: aiContext };
        if (query && query.trim()) {
            bodyPayload.query = query.trim();
        }
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/ai/plan`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(bodyPayload),
        });
        return this.parseResponse<AIPlanResponse>(response, 'Failed to generate AI plan');
    }

    /**
     * Download Editor Brief as a Word (.docx) document
     */
    async downloadEditorBrief(request: BriefExportRequest): Promise<void> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/export/brief`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });

        if (!response.ok) {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err?.detail || 'Failed to download editor brief');
            }
            throw new Error(SERVER_BUSY_MESSAGE);
        }

        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition');
        let filename = 'geo-brief.docx';
        if (disposition && disposition.includes('filename=')) {
            const match = disposition.match(/filename="?([^"]+)"?/);
            if (match && match[1]) filename = match[1];
        }

        const blobUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(blobUrl);
    }

    /**
     * Fetch off-page authority and ranking signals from Ahrefs
     */
    async checkOffpage(url: string, language?: string): Promise<AhrefsOffpageResponse> {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/offpage`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url, language: language || 'en' }),
        });
        return this.parseResponse<AhrefsOffpageResponse>(response, 'Failed to fetch Ahrefs off-page signals');
    }
}

export const apiClient = new ApiClient();
export default apiClient;
