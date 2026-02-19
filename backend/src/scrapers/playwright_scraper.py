"""
GEO-AUDITOR AI - Playwright Scraper

Full-featured web scraper using Playwright for JavaScript rendering.
Capable of detecting SSR vs CSR pages by comparing raw HTML to rendered DOM.

Key Features:
- SSR/CSR detection via content comparison
- HTTPS validation
- Response header capture
- Graceful timeout handling (per best practices)
- Word count calculation

Performance Target: Complete scraping in <30s (leaving 30s for analysis per SRS)
"""

import re
import time
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, Response

from src.models.schemas import PageData
from src.scrapers.base_scraper import BaseScraper, ScraperError
from config.settings import get_settings


class PlaywrightScraper(BaseScraper):
    """
    Playwright-based scraper with SSR/CSR detection.
    
    Uses headless Chromium to render pages and detect whether they
    rely on client-side or server-side rendering. This is critical
    for Technical Infrastructure scoring (Layer 1).
    
    Example:
        >>> async with PlaywrightScraper() as scraper:
        ...     data = await scraper.scrape("https://stripe.com")
        ...     print(f"SSR: {data.is_ssr}, HTTPS: {data.is_https}")
        SSR: True, HTTPS: True
        
    Attributes:
        browser: The Playwright browser instance
        settings: Application settings for timeouts, etc.
    """
    
    def __init__(self):
        """Initialize scraper with settings."""
        self.settings = get_settings()
        self._playwright = None
        self._browser: Optional[Browser] = None
    
    async def _ensure_browser(self) -> Browser:
        """
        Lazily initialize the browser instance.
        
        Returns:
            Playwright Browser instance
        """
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
        return self._browser
    
    async def scrape(self, url: str) -> PageData:
        """
        Scrape a URL with full JavaScript rendering.
        
        Performs the following steps:
        1. Fetch raw HTML (without JS execution) via initial response
        2. Wait for full page render
        3. Compare raw vs rendered to detect SSR/CSR
        4. Extract text content and metadata
        
        Args:
            url: URL to scrape (HTTP or HTTPS)
            
        Returns:
            PageData with all scraped information
            
        Raises:
            ScraperError: If page cannot be loaded or times out
        """
        # Validate URL protocol
        if not url.startswith(("http://", "https://")):
            raise ScraperError(url, "Invalid URL protocol. Must be HTTP or HTTPS.")
        
        browser = await self._ensure_browser()
        
        # Real Human-like Headers
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={'width': 1920, 'height': 1080},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        page = await context.new_page()
        
        start_time = time.time()
        response_headers: dict[str, str] = {}
        status_code = 0
        html_raw = ""
        
        try:
            # Capture the initial response
            def handle_response(response: Response):
                nonlocal response_headers, status_code, html_raw
                if response.url == url or response.url.rstrip("/") == url.rstrip("/"):
                    response_headers = dict(response.headers)
                    status_code = response.status
            
            page.on("response", handle_response)
            
            # Navigate and capture initial HTML
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.scraper_timeout_ms
            )
            
            if response:
                status_code = response.status
                response_headers = dict(response.headers)
                # Get raw HTML
                html_raw = await page.content()
            
            # BLOCK DETECTION
            title = await page.title()
            block_indicators = ["Access Denied", "Not Available", "403", "Captcha", "Security Check"]
            if any(indicator.lower() in title.lower() for indicator in block_indicators):
                raise ScraperError(url, "⛔ Scraper Blocked by Website Security (Access Denied / 403)")
            
            # Check for French block message mentioned by user
            body_text = await page.inner_text("body")
            if "Cet Article N'est Pas Encore Disponible" in body_text:
                raise ScraperError(url, "⛔ Scraper Blocked: Article Not Available (Geo-block/Error)")

            # Wait for full render (network idle)
            # INCREASED TIMEOUT FOR PRODUCTION STABILITY
            try:
                await page.wait_for_load_state(
                    self.settings.scraper_wait_until,
                    timeout=self.settings.scraper_timeout_ms
                )
                # Additional small grace period for slow SPAs to settle
                await page.wait_for_timeout(2000) 
            except Exception as e:
                # If networkidle fails, we still try to proceed with what we have
                print(f"Warning: wait_for_load_state timed out/failed: {str(e)}")
            
            # Get rendered HTML after JS execution
            html_rendered = await page.content()
            
            # Extract text content
            text_content = await self._extract_text_content(page)
            
            # Calculate load time
            load_time_ms = (time.time() - start_time) * 1000
            
            # Detect SSR vs CSR
            is_ssr = self._detect_ssr(html_raw, html_rendered)
            
            # Check HTTPS
            is_https = url.startswith("https://")
            
            # Calculate word count
            word_count = len(text_content.split())
            
            # Get final URL (after redirects)
            final_url = page.url
            
            return PageData(
                url=url,
                final_url=final_url,
                html_raw=html_raw,
                html_rendered=html_rendered,
                text_content=text_content,
                headers=response_headers,
                status_code=status_code,
                load_time_ms=load_time_ms,
                scraped_at=datetime.utcnow(),
                is_https=is_https,
                is_ssr=is_ssr,
                word_count=word_count,
            )
            
        except Exception as e:
            raise ScraperError(
                url=url,
                reason=f"Failed to load page: {str(e)}",
                original_error=e
            )
        finally:
            await context.close()
    
    async def _extract_text_content(self, page: Page) -> str:
        """
        Extract visible text content from the page using aggressive cleaning.
        """
        from src.utils.text_processing import extract_clean_text
        
        # Get rendered HTML
        html_rendered = await page.content()
        
        # Use our backend cleaning utility
        clean_text = extract_clean_text(html_rendered)
        
        return clean_text
    
    def _detect_ssr(self, html_raw: str, html_rendered: str) -> bool:
        """
        Detect if the page uses Server-Side Rendering (SSR) or Client-Side Rendering (CSR).
        
        Comparison Logic:
        - SSR pages have most content in the initial HTML (before JS)
        - CSR pages (SPAs) have minimal initial HTML, JS populates content
        
        Heuristic: If rendered HTML is >50% larger than raw HTML, likely CSR.
        If raw HTML already contains substantial body content, likely SSR.
        
        Args:
            html_raw: HTML from initial page load (before JS completes)
            html_rendered: HTML after full JS execution
            
        Returns:
            True if SSR, False if CSR
        """
        # Remove whitespace for fair comparison
        raw_length = len(html_raw.replace(" ", "").replace("\n", ""))
        rendered_length = len(html_rendered.replace(" ", "").replace("\n", ""))
        
        if raw_length == 0:
            return False  # Empty raw = definitely CSR
        
        # Calculate content increase ratio
        increase_ratio = rendered_length / raw_length if raw_length > 0 else float('inf')
        
        # Check for common SSR indicators in raw HTML
        ssr_indicators = [
            # Has substantial body content
            len(re.findall(r'<p[^>]*>.*?</p>', html_raw, re.DOTALL)) > 2,
            # Has multiple heading tags
            len(re.findall(r'<h[1-6][^>]*>.*?</h[1-6]>', html_raw, re.DOTALL)) > 1,
            # Has article/section structure
            '<article' in html_raw.lower() or '<main' in html_raw.lower(),
        ]
        
        # If raw HTML has these indicators AND content didn't grow much, it's SSR
        has_ssr_indicators = sum(ssr_indicators) >= 2
        content_stable = increase_ratio < 1.5
        
        return has_ssr_indicators or content_stable
    
    async def close(self) -> None:
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
