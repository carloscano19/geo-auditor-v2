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

export interface TopicIssue {
    dimension: string;
    submetric: string;
    affected_count: number;
    affected_urls: string[];
    top_recommendation?: string;
    impact: number;
}

export interface BatchJobResponse {
    job_id: string;
    status: 'pending' | 'running' | 'done';
    total: number;
    completed: number;
    results: BatchItemResult[];
    issues_by_topic: TopicIssue[];
    created_at: string;
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
            const error = await response.json();
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
    async getVersion(): Promise<{ version: string }> {
        const response = await fetch(`${this.baseUrl}/api/version`);
        if (!response.ok) {
            throw new Error('Failed to fetch version');
        }
        return response.json();
    }
}

export const apiClient = new ApiClient();
export default apiClient;
