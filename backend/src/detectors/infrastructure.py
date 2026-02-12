"""
GEO-AUDITOR AI - Infrastructure Detector

Layer 1: Technical Infrastructure (12% of total score)

Evaluates the technical foundation of a page that affects
its discoverability and processability by LLMs and crawlers.

Sub-metrics evaluated (from SRS):
- HTTPS: Security protocol (25% of layer)
- SSR Detection: Server-side vs client-side rendering (30% of layer)
- Crawlability: Robots meta, X-Robots-Tag (25% of layer)
- Render Speed: Page load performance (20% of layer)

Performance Target: Detection should complete in <5 seconds
(allowing 55s for other dimensions per SRS 60s total target)
"""

import re
from typing import Optional
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from config.settings import get_settings


class InfrastructureDetector(BaseDetector):
    """
    Technical Infrastructure Detector.
    
    Evaluates Layer 1 criteria from SRS Section 3:
    "1. Infraestructura Técnica | 12% | SSR/CSR, Crawlability, Renderizado"
    
    This detector analyzes:
    1. HTTPS security (binary check)
    2. SSR vs CSR detection (from scraper data)
    3. Crawlability signals (robots meta, headers)
    4. Render speed (load time thresholds)
    
    Example:
        >>> detector = InfrastructureDetector()
        >>> result = await detector.analyze(page_data)
        >>> for item in result.breakdown:
        ...     print(f"{item.name}: {item.raw_score}")
        HTTPS Security: 100.0
        Rendering Mode: 100.0
        Crawlability: 85.0
        Page Load Speed: 90.0
        
    Attributes:
        dimension_name: "technical_infrastructure"
        weight: 0.12 (12% of total score)
    """
    
    dimension_name: str = "technical_infrastructure"
    weight: float = 0.12
    
    # Sub-dimension weights (from SRS best practices)
    HTTPS_WEIGHT = 0.25
    SSR_WEIGHT = 0.30
    CRAWLABILITY_WEIGHT = 0.25
    SPEED_WEIGHT = 0.20
    
    # Speed thresholds (milliseconds)
    SPEED_EXCELLENT = 2000   # <2s = 100 points
    SPEED_GOOD = 4000        # <4s = 80 points
    SPEED_ACCEPTABLE = 6000  # <6s = 60 points
    SPEED_POOR = 10000       # <10s = 30 points
    # >10s = 0 points
    
    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()
        
        # Load weights from config if available
        try:
            weights = self.settings.scoring_weights
            infra_config = weights.get("dimensions", {}).get("technical_infrastructure", {})
            self.weight = infra_config.get("weight", self.weight)
            
            subdims = infra_config.get("subdimensions", {})
            self.HTTPS_WEIGHT = subdims.get("https", self.HTTPS_WEIGHT)
            self.SSR_WEIGHT = subdims.get("ssr_detection", self.SSR_WEIGHT)
            self.CRAWLABILITY_WEIGHT = subdims.get("crawlability", self.CRAWLABILITY_WEIGHT)
            self.SPEED_WEIGHT = subdims.get("render_speed", self.SPEED_WEIGHT)
        except Exception:
            pass  # Use defaults if config fails
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """
        Analyze technical infrastructure of the page.
        
        Evaluates all sub-metrics and combines them into
        a weighted dimension score.
        
        Args:
            page_data: Scraped page content and metadata
            
        Returns:
            DetectorResult with full breakdown and recommendations
        """
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        
        # 1. HTTPS Security Check
        try:
            https_result = self._analyze_https(page_data)
            breakdown.append(https_result)
        except Exception as e:
            errors.append(f"HTTPS check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("HTTPS Security", self.HTTPS_WEIGHT))
        
        # 2. SSR/CSR Detection
        try:
            ssr_result = self._analyze_ssr(page_data)
            breakdown.append(ssr_result)
        except Exception as e:
            errors.append(f"SSR detection failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Rendering Mode", self.SSR_WEIGHT))
        
        # 3. Crawlability Check
        try:
            crawl_result = self._analyze_crawlability(page_data)
            breakdown.append(crawl_result)
        except Exception as e:
            errors.append(f"Crawlability check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Crawlability", self.CRAWLABILITY_WEIGHT))
        
        # 4. Render Speed Check
        try:
            speed_result = self._analyze_speed(page_data)
            breakdown.append(speed_result)
        except Exception as e:
            errors.append(f"Speed check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Page Load Speed", self.SPEED_WEIGHT))
        
        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
        )
    
    
    def _analyze_https(self, page_data: PageData) -> ScoreBreakdown:
        """
        Analyze HTTPS security.
        """
        is_https = page_data.is_https
        raw_score = 100.0 if is_https else 0.0
        
        recommendations = []
        if not is_https:
            recommendations.append(
                "CRITICAL: Migrate to HTTPS. LLMs prioritize secure sources."
            )
        
        explanation = (
            "Secure HTTPS connection detected." if is_https
            else "Page served via insecure HTTP. This affects reliability."
        )
        
        return ScoreBreakdown(
            name="HTTPS Security",
            raw_score=raw_score,
            weight=self.HTTPS_WEIGHT,
            weighted_score=raw_score * self.HTTPS_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_ssr(self, page_data: PageData) -> ScoreBreakdown:
        """
        Analyze rendering mode (SSR vs CSR).
        """
        is_ssr = page_data.is_ssr
        
        if is_ssr:
            raw_score = 100.0
            explanation = (
                "Server-Side Rendering (SSR) detected. "
                "Content is immediately available for crawlers and LLMs."
            )
            recommendations = []
        else:
            # Check if there's meaningful content in raw HTML (hybrid approach)
            raw_has_content = len(page_data.html_raw) > 5000
            
            if raw_has_content:
                raw_score = 50.0
                explanation = (
                    "Client-Side Rendering (CSR) with partial initial content. "
                    "Some LLMs might not capture full context."
                )
                recommendations = [
                    "Consider implementing SSR or pre-rendering to improve indexing.",
                ]
            else:
                raw_score = 20.0
                explanation = (
                    "Pure Client-Side Rendering (CSR) detected. "
                    "Initial HTML contains only app shell."
                )
                recommendations = [
                    "IMPORTANT: Implement SSR, SSG, or pre-rendering.",
                    "LLM crawlers (ChatGPT, Gemini) might not execute JavaScript.",
                    "Content invisible to generative answer engines."
                ]
        
        return ScoreBreakdown(
            name="Rendering Mode (SSR/CSR)",
            raw_score=raw_score,
            weight=self.SSR_WEIGHT,
            weighted_score=raw_score * self.SSR_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_crawlability(self, page_data: PageData) -> ScoreBreakdown:
        """
        Analyze crawlability signals.
        """
        html = page_data.html_rendered.lower()
        headers = {k.lower(): v.lower() for k, v in page_data.headers.items()}
        
        # Check for robots meta tag
        robots_meta_match = re.search(
            r'<meta[^>]*name=["\']robots["\'][^>]*content=["\']([^"\']+)["\']',
            html
        )
        robots_content = robots_meta_match.group(1) if robots_meta_match else ""
        
        # Check X-Robots-Tag header
        x_robots = headers.get("x-robots-tag", "")
        
        # Combine directives
        all_directives = f"{robots_content} {x_robots}".lower()
        
        has_noindex = "noindex" in all_directives
        has_nofollow = "nofollow" in all_directives
        has_none = "none" in all_directives
        
        # Check for canonical
        has_canonical = '<link' in html and 'rel="canonical"' in html
        
        recommendations = []
        
        if has_noindex or has_none:
            raw_score = 0.0
            explanation = (
                "BLOCKED: 'noindex' directive detected. "
                "This page will not be indexed or cited by LLMs."
            )
            recommendations.append(
                "Remove 'noindex' if you want this page to be cited by AI."
            )
        elif has_nofollow:
            raw_score = 70.0
            explanation = (
                "'nofollow' directive detected. Page is indexable "
                "but links won't be followed to discover related content."
            )
            recommendations.append(
                "Consider removing 'nofollow' to improve content discovery."
            )
        else:
            raw_score = 100.0 if has_canonical else 90.0
            explanation = (
                "Page fully crawlable without restrictions. "
                + ("Canonical URL defined." if has_canonical else "")
            )
            if not has_canonical:
                recommendations.append(
                    "Add canonical tag to avoid duplicate content issues."
                )
        
        return ScoreBreakdown(
            name="Crawlability",
            raw_score=raw_score,
            weight=self.CRAWLABILITY_WEIGHT,
            weighted_score=raw_score * self.CRAWLABILITY_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_speed(self, page_data: PageData) -> ScoreBreakdown:
        """
        Analyze page load speed.
        """
        load_time_ms = page_data.load_time_ms
        
        if load_time_ms < self.SPEED_EXCELLENT:
            raw_score = 100.0
            status = "excellent"
        elif load_time_ms < self.SPEED_GOOD:
            raw_score = 80.0
            status = "good"
        elif load_time_ms < self.SPEED_ACCEPTABLE:
            raw_score = 60.0
            status = "acceptable"
        elif load_time_ms < self.SPEED_POOR:
            raw_score = 30.0
            status = "slow"
        else:
            raw_score = 0.0
            status = "critical"
        
        load_time_s = load_time_ms / 1000
        explanation = (
            f"Load Time: {load_time_s:.2f}s ({status}). "
            f"{'Within performance target.' if raw_score >= 60 else 'Requires urgent optimization.'}"
        )
        
        recommendations = []
        if raw_score < 100:
            recommendations.append(
                f"Goal: reduce load time to <2s (currently {load_time_s:.1f}s)."
            )
        if raw_score < 60:
            recommendations.extend([
                "Check Core Web Vitals in PageSpeed Insights.",
                "Optimize images, critical CSS, and lazy loading.",
            ])
        
        return ScoreBreakdown(
            name="Page Load Speed",
            raw_score=raw_score,
            weight=self.SPEED_WEIGHT,
            weighted_score=raw_score * self.SPEED_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _create_error_breakdown(self, name: str, weight: float) -> ScoreBreakdown:
        """Create a zero-score breakdown for failed checks."""
        return ScoreBreakdown(
            name=name,
            raw_score=0.0,
            weight=weight,
            weighted_score=0.0,
            explanation=f"Error analyzing {name}. Score: 0.",
            recommendations=[f"Manual verification required: {name}."],
        )
