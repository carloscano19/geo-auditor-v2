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
import urllib.robotparser
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from config.settings import get_settings


class InfrastructureDetector(BaseDetector):
    """
    Technical Infrastructure Detector.
    
    Evaluates Layer 1 criteria:
    1. HTTPS security (binary check)
    2. SSR vs CSR detection (from scraper data)
    3. Crawlability signals (robots meta, headers)
    4. AI Bot Access (robots.txt permissions for search & training bots, nosnippet)
    5. Render speed (TTFB thresholds)
    """
    
    dimension_name: str = "technical_infrastructure"
    weight: float = 0.10
    
    # Sub-dimension weights (5 subdimensions)
    HTTPS_WEIGHT = 0.20
    SSR_WEIGHT = 0.20
    CRAWLABILITY_WEIGHT = 0.20
    AI_BOT_ACCESS_WEIGHT = 0.20
    SPEED_WEIGHT = 0.20
    
    # Speed (TTFB) thresholds (milliseconds)
    TTFB_EXCELLENT = 800   # <800ms = 100 points
    TTFB_GOOD = 1500       # <1500ms = 80 points
    TTFB_ACCEPTABLE = 3000 # <3000ms = 50 points
    # >=3000ms or timeout = 20 points
    
    SEARCH_BOTS = [
        "OAI-SearchBot",
        "ChatGPT-User",
        "PerplexityBot",
        "Claude-SearchBot",
    ]
    TRAINING_BOTS = [
        "GPTBot",
        "ClaudeBot",
        "Google-Extended",
    ]
    
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
            self.AI_BOT_ACCESS_WEIGHT = subdims.get("ai_bot_access", self.AI_BOT_ACCESS_WEIGHT)
            self.SPEED_WEIGHT = subdims.get("render_speed", self.SPEED_WEIGHT)
        except Exception:
            pass  # Use defaults if config fails
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """
        Analyze technical infrastructure of the page.
        """
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        has_critical_bot_block = False
        critical_block_reasons = []
        
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
            crawl_result, crawl_is_critical, crawl_reason = self._analyze_crawlability(page_data)
            breakdown.append(crawl_result)
            if crawl_is_critical:
                has_critical_bot_block = True
                if crawl_reason:
                    critical_block_reasons.append(crawl_reason)
        except Exception as e:
            errors.append(f"Crawlability check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Crawlability", self.CRAWLABILITY_WEIGHT))
        
        # 4. AI Bot Access Check
        try:
            bot_result, bot_is_critical, bot_reason = self._analyze_ai_bot_access(page_data)
            breakdown.append(bot_result)
            if bot_is_critical:
                has_critical_bot_block = True
                if bot_reason:
                    critical_block_reasons.append(bot_reason)
        except Exception as e:
            errors.append(f"AI Bot Access check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("AI Bot Access", self.AI_BOT_ACCESS_WEIGHT))
        
        # 5. Render Speed Check
        try:
            speed_result = self._analyze_speed(page_data)
            breakdown.append(speed_result)
        except Exception as e:
            errors.append(f"Speed check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Page Load Speed", self.SPEED_WEIGHT))
        
        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        debug_info = {}
        if has_critical_bot_block:
            debug_info["has_critical_bot_block"] = True
            debug_info["critical_block_reasons"] = critical_block_reasons
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
            debug_info=debug_info,
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
    
    def _analyze_crawlability(self, page_data: PageData) -> Tuple[ScoreBreakdown, bool, Optional[str]]:
        """
        Analyze crawlability signals.
        Returns: (ScoreBreakdown, is_critical_block, critical_reason)
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
        has_nosnippet = "nosnippet" in all_directives
        has_max_snippet_0 = bool(re.search(r'max-snippet\s*:\s*0\b', all_directives))
        
        # Check data-nosnippet elements in HTML
        soup = BeautifulSoup(page_data.html_rendered, 'lxml')
        has_data_nosnippet = bool(soup.find(attrs={"data-nosnippet": True}))
        
        # Check for canonical
        has_canonical = '<link' in html and 'rel="canonical"' in html
        
        recommendations = []
        is_critical = False
        critical_reason = None
        
        if has_noindex or has_none:
            raw_score = 0.0
            is_critical = True
            critical_reason = "Page blocked by 'noindex' directive in robots meta/header."
            explanation = (
                "BLOCKED: 'noindex' directive detected. "
                "This page will not be indexed or cited by LLMs."
            )
            recommendations.append(
                "CRITICAL: Remove 'noindex' if you want this page to be cited by AI."
            )
        elif has_nosnippet or has_max_snippet_0:
            raw_score = 10.0
            is_critical = True
            directive_name = "nosnippet" if has_nosnippet else "max-snippet:0"
            critical_reason = f"Page blocked by '{directive_name}' directive in robots meta/header."
            explanation = (
                f"RESTRICTED: '{directive_name}' directive detected. "
                "AI search engines cannot extract answer snippets."
            )
            recommendations.append(
                f"CRITICAL: Remove '{directive_name}' so AI search engines can cite content snippets."
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
        
        if has_data_nosnippet:
            explanation += " (Note: HTML elements with 'data-nosnippet' detected, parts of content hidden from snippets)."
            recommendations.append("Review 'data-nosnippet' attributes to ensure key definitions and data remain extractable by AI.")
        
        breakdown = ScoreBreakdown(
            name="Crawlability",
            raw_score=raw_score,
            weight=self.CRAWLABILITY_WEIGHT,
            weighted_score=raw_score * self.CRAWLABILITY_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
        return breakdown, is_critical, critical_reason

    def _analyze_ai_bot_access(self, page_data: PageData) -> Tuple[ScoreBreakdown, bool, Optional[str]]:
        """
        Analyze AI Bot Access via robots.txt and snippet directives.
        Evaluates search bots (OAI-SearchBot, ChatGPT-User, PerplexityBot, Claude-SearchBot)
        and training bots (GPTBot, ClaudeBot, Google-Extended).
        Returns: (ScoreBreakdown, is_critical_block, critical_reason)
        """
        rp = urllib.robotparser.RobotFileParser()
        robots_content = page_data.robots_txt_content
        
        if robots_content:
            rp.parse(robots_content.splitlines())
        else:
            # If robots.txt doesn't exist or failed to load, everything is allowed
            rp.parse(["User-agent: *", "Allow: /"])
        
        target_url = page_data.final_url or page_data.url or "https://example.com/"
        
        search_status = {}
        for bot in self.SEARCH_BOTS:
            allowed = rp.can_fetch(bot, target_url) if robots_content else True
            search_status[bot] = allowed
            
        training_status = {}
        for bot in self.TRAINING_BOTS:
            allowed = rp.can_fetch(bot, target_url) if robots_content else True
            training_status[bot] = allowed
            
        blocked_search = [bot for bot, allowed in search_status.items() if not allowed]
        blocked_training = [bot for bot, allowed in training_status.items() if not allowed]
        
        # Build explanation with bot status
        search_details = [f"{bot}: {'Allowed' if allowed else 'Blocked'}" for bot, allowed in search_status.items()]
        training_details = [f"{bot}: {'Allowed' if allowed else 'Blocked'}" for bot, allowed in training_status.items()]
        
        is_critical = False
        critical_reason = None
        recommendations = []
        
        if blocked_search:
            raw_score = 0.0
            is_critical = True
            critical_reason = f"robots.txt blocks AI search bots: {', '.join(blocked_search)}."
            explanation = (
                f"CRITICAL: AI search bots blocked ({', '.join(blocked_search)}). "
                f"Search bots: [{'; '.join(search_details)}]. "
                f"Training bots: [{'; '.join(training_details)}]."
            )
            recommendations.append(
                f"CRITICAL: Allow AI search bots ({', '.join(blocked_search)}) in /robots.txt to appear in AI answers."
            )
        elif blocked_training:
            raw_score = 80.0
            explanation = (
                f"AI search bots allowed. Training bots restricted ({', '.join(blocked_training)}). "
                f"Search bots: [{'; '.join(search_details)}]. "
                f"Training bots: [{'; '.join(training_details)}]."
            )
            recommendations.append(
                f"Informational: Training bots ({', '.join(blocked_training)}) are blocked in /robots.txt. Search bots are allowed."
            )
        else:
            raw_score = 100.0
            explanation = (
                "All major AI search and training bots allowed in robots.txt. "
                f"Search bots: [{'; '.join(search_details)}]. "
                f"Training bots: [{'; '.join(training_details)}]."
            )
            
        breakdown = ScoreBreakdown(
            name="AI Bot Access",
            raw_score=raw_score,
            weight=self.AI_BOT_ACCESS_WEIGHT,
            weighted_score=raw_score * self.AI_BOT_ACCESS_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
        return breakdown, is_critical, critical_reason
    
    def _analyze_speed(self, page_data: PageData) -> ScoreBreakdown:
        """
        Analyze page load speed using TTFB (Time To First Byte).
        """
        ttfb_ms = page_data.ttfb_ms
        recommendations = []
        
        if ttfb_ms is None:
            raw_score = 20.0
            explanation = "TTFB measurement failed or timed out. Default score applied: 20."
            recommendations.append("Ensure server responds promptly to initial HTTP GET requests (<800ms).")
        elif ttfb_ms < self.TTFB_EXCELLENT:
            raw_score = 100.0
            status = "excellent"
            explanation = f"TTFB: {ttfb_ms:.0f}ms ({status}). Server response is optimal for AI crawlers."
        elif ttfb_ms < self.TTFB_GOOD:
            raw_score = 80.0
            status = "good"
            explanation = f"TTFB: {ttfb_ms:.0f}ms ({status}). Good server response time."
            recommendations.append(f"Goal: reduce TTFB to <800ms (currently {ttfb_ms:.0f}ms).")
        elif ttfb_ms < self.TTFB_ACCEPTABLE:
            raw_score = 50.0
            status = "acceptable"
            explanation = f"TTFB: {ttfb_ms:.0f}ms ({status}). Server response is slower than optimal."
            recommendations.extend([
                f"Reduce server response time (TTFB currently {ttfb_ms:.0f}ms, aim for <800ms).",
                "Consider edge caching (CDN) or backend query optimization."
            ])
        else:
            raw_score = 20.0
            status = "slow"
            explanation = f"TTFB: {ttfb_ms:.0f}ms ({status}). Slow server response."
            recommendations.extend([
                f"Critical: Reduce TTFB (currently {ttfb_ms:.0f}ms, aim for <800ms).",
                "Slow initial server response delays AI crawler indexing and citability."
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
