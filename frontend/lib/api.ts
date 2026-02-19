/**
 * GEO-AUDITOR AI - API Client
 * 
 * Centralized API client for communicating with the FastAPI backend.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface AuditRequest {
    url?: string;
    content_text?: string;
    platform_target?: 'chatgpt' | 'gemini' | 'perplexity' | 'copilot' | 'universal';
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
    debug_info?: any;
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
    analysis_time_ms: number;
    analyzed_at: string;
    recommendations: string[];
    detector_results: DetectorResult[];
}

export interface HealthStatus {
    status: string;
    version: string;
    timestamp: string;
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
     * Run optimization on audit results
     */
    async optimize(data: {
        content_text: string;
        audit_results: AuditResponse;
        provider: string;
        api_key: string;
    }): Promise<{ optimized_content: string }> {
        const response = await fetch(`${this.baseUrl}/api/optimize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Optimization failed');
        }

        return response.json();
    }
}

export const apiClient = new ApiClient();
export default apiClient;
