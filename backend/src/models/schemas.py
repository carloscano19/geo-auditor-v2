"""
GEO-AUDITOR AI - Pydantic Schemas

Data models for the audit system following immutable data principles.
Each pipeline stage produces new objects, never mutating existing ones.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl


class AuditRequest(BaseModel):
    """
    Request model for initiating a content audit.
    
    Attributes:
        url: The URL to audit (optional if content_text is provided)
        content_text: Raw text content to audit directly (bypasses scraping)
        platform_target: Optional target platform for optimization hints
    """
    url: Optional[str] = Field(None, description="URL to audit")
    content_text: Optional[str] = Field(None, description="Raw text content to analyze directly")
    platform_target: Optional[str] = Field(
        default="universal",
        description="Target platform: chatgpt, gemini, perplexity, copilot, or universal"
    )


class PageData(BaseModel):
    """
    Scraped page data container.
    
    Immutable representation of page content extracted during scraping phase.
    This object flows through the processing pipeline without mutation.
    
    Attributes:
        url: Original URL that was scraped
        final_url: Final URL after redirects
        html_raw: Raw HTML before JavaScript execution
        html_rendered: HTML after JavaScript execution (for CSR detection)
        text_content: Extracted text content
        headers: HTTP response headers
        status_code: HTTP status code
        load_time_ms: Time to load the page in milliseconds
        scraped_at: Timestamp of when the page was scraped
    """
    url: str
    final_url: str
    html_raw: str
    html_rendered: str
    text_content: str
    headers: dict[str, str] = Field(default_factory=dict)
    status_code: int
    load_time_ms: float
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Computed properties from scraping
    is_https: bool = False
    is_ssr: bool = True  # True if SSR, False if CSR
    word_count: int = 0


class ScoreBreakdown(BaseModel):
    """
    Individual score component with explanation.
    
    Provides transparency for each score calculation as required by SRS.
    Users can understand exactly why they received a specific score.
    
    Attributes:
        name: Name of the scored component
        raw_score: Score before weight application (0-100)
        weight: Weight multiplier for this component
        weighted_score: Final contribution to dimension score
        explanation: Human-readable explanation of the score
        recommendations: List of actionable improvements
    """
    name: str
    raw_score: float = Field(..., ge=0, le=100)
    weight: float = Field(..., ge=0, le=1)
    weighted_score: float = Field(..., ge=0, le=100)
    explanation: str
    recommendations: list[str] = Field(default_factory=list)


class DetectorResult(BaseModel):
    """
    Result from a single detector module.
    
    Each detector (infrastructure, metadata, etc.) produces this output.
    Contains the dimension score plus detailed breakdown.
    
    Attributes:
        dimension: Name of the evaluated dimension
        score: Overall dimension score (0-100)
        weight: Dimension weight in total score
        contribution: Contribution to total score
        breakdown: Detailed score components
        errors: Any errors encountered during analysis
    """
    dimension: str
    score: float = Field(..., ge=0, le=100)
    weight: float = Field(..., ge=0, le=1)
    contribution: float = Field(..., ge=0, le=100)
    breakdown: list[ScoreBreakdown]
    errors: list[str] = Field(default_factory=list)
    debug_info: Dict[str, Any] = Field(default_factory=dict, description="Transparency data (detected headers, entities, etc)")
    
    @property
    def status(self) -> str:
        """Return status color based on score."""
        if self.score >= 80:
            return "green"
        elif self.score >= 50:
            return "yellow"
        return "red"


class DimensionScore(BaseModel):
    """Summary of a dimension score for the response."""
    name: str
    score: float
    weight: float
    contribution: float
    status: str  # green, yellow, red


class OptimizeRequest(BaseModel):
    content_text: str
    audit_results: Dict[str, Any]
    provider: str = "openai"
    api_key: str

class OptimizeResponse(BaseModel):
    optimized_content: str


class AuditResponse(BaseModel):
    """
    Complete audit response.
    
    Contains the overall score, dimensional breakdown, and metadata.
    This is the primary response object sent to the frontend.
    
    Attributes:
        url: The audited URL
        total_score: Overall citability score (0-100)
        dimensions: Scores per dimension
        scoring_version: Version of scoring algorithm used
        analysis_time_ms: Total analysis time in milliseconds
        analyzed_at: Timestamp of analysis
        recommendations: Top prioritized recommendations
    """
    url: str
    total_score: float = Field(..., ge=0, le=100)
    dimensions: list[DimensionScore]
    scoring_version: str
    analysis_time_ms: float
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    recommendations: list[str] = Field(default_factory=list)
    
    # Raw detector results for detailed view
    detector_results: list[DetectorResult] = Field(default_factory=list)
