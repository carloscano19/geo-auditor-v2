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

class ApiClient {
    private baseUrl: string;

    constructor(baseUrl: string = API_BASE_URL) {
        this.baseUrl = baseUrl;
    }

    /**
     * Check API health status
     */
    async health(): Promise<HealthStatus> {
        const response = await fetch(`${this.baseUrl}/api/health`);
        if (!response.ok) {
            throw new Error('API is not available');
        }
        return response.json();
    }

    /**
     * Run audit on a URL
     */
    async audit(request: AuditRequest): Promise<AuditResponse> {
        const response = await fetch(`${this.baseUrl}/api/audit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Audit failed');
        }

        return response.json();
    }

    /**
     * Start a batch audit
     */
    async startBatch(request: BatchAuditRequest): Promise<{ job_id: string }> {
        const response = await fetch(`${this.baseUrl}/api/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Batch audit initiation failed');
        }

        return response.json();
    }

    /**
     * Get batch job status
     */
    async getBatchStatus(jobId: string): Promise<BatchJobResponse> {
        const response = await fetch(`${this.baseUrl}/api/batch/${jobId}`);
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to get batch status');
        }
        return response.json();
    }

    /**
     * Get batch CSV download URL
     */
    getBatchCsvUrl(jobId: string): string {
        return `${this.baseUrl}/api/batch/${jobId}/csv`;
    }

    /**
     * Get batch issues CSV download URL
     */
    getBatchIssuesCsvUrl(jobId: string): string {
        return `${this.baseUrl}/api/batch/${jobId}/issues.csv`;
    }

    /**
     * Get scoring weights configuration
     */
    async getScoringWeights(): Promise<Record<string, unknown>> {
        const response = await fetch(`${this.baseUrl}/api/scoring-weights`);
        if (!response.ok) {
            throw new Error('Failed to fetch scoring weights');
        }
        return response.json();
    }

    /**
     * Get backend version (single source of truth)
     */
    async getVersion(): Promise<{ version: string; ai_enabled?: boolean; serp_enabled?: boolean }> {
        const response = await fetch(`${this.baseUrl}/api/version`);
        if (!response.ok) {
            throw new Error('Failed to fetch version');
        }
        return response.json();
    }

    /**
     * Generate AI suggested fixes for Schema.org and lead paragraph
     */
    async generateAIFixes(aiContext: AIContext): Promise<AIFixesResponse> {
        const response = await fetch(`${this.baseUrl}/api/ai/fixes`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ai_context: aiContext }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to generate AI fixes');
        }

        return response.json();
    }

    /**
     * Generate comprehensive AI improvement plan
     */
    async generateAIPlan(aiContext: AIContext): Promise<AIPlanResponse> {
        const response = await fetch(`${this.baseUrl}/api/ai/plan`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ai_context: aiContext }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to generate AI plan');
        }

        return response.json();
    }
}

export const apiClient = new ApiClient();
export default apiClient;
