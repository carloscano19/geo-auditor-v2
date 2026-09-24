"""
GEO-AUDITOR AI - FastAPI Application

Main entry point for the GEO-AUDITOR AI backend.
Provides REST API endpoints for content citability auditing.

API Endpoints:
- POST /api/audit: Analyze a URL for LLM citability
- GET /api/health: Health check endpoint
- GET /api/scoring-weights: Get current scoring configuration

CORS is configured to allow the Next.js frontend (localhost:3000).
"""

import time
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from src.models.schemas import (
    AuditRequest,
    AuditResponse,
    DimensionScore,
    PageData,
)
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.scrapers.base_scraper import ScraperError
from src.detectors.infrastructure import InfrastructureDetector
from src.detectors.evidence_density import EvidenceDensityDetector
from src.utils.lang_patterns import detect_language

logger = logging.getLogger("geo_auditor")

# Global scraper instance (reused across requests for performance)
scraper: PlaywrightScraper = None

# Concurrency limiter: ensure only 1 Playwright scraping session runs at a time
scrape_semaphore = asyncio.Semaphore(1)


async def measure_ttfb(url: str) -> Optional[float]:
    """
    Measure Time To First Byte (TTFB) using an independent HTTP GET request with httpx.
    Uses client.stream to stop timing as soon as response headers arrive without reading the body.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": user_agent}
    start_time = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                ttfb_ms = (time.perf_counter() - start_time) * 1000
                return ttfb_ms
    except Exception as e:
        logger.warning(f"TTFB measurement failed for {url}: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Initializes and cleans up resources like the Playwright browser.
    """
    global scraper
    scraper = PlaywrightScraper()
    yield
    # Cleanup
    if scraper:
        await scraper.close()


# Initialize FastAPI app
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Advanced GEO/AEO Audit System for LLM Citability Optimization",
    lifespan=lifespan,
)

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        dict: Status and version information
    """
    return {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/version")
async def get_version():
    """
    Single source of version endpoint.
    
    Returns:
        dict: Application and scoring version
    """
    return {
        "version": settings.app_version,
    }


@app.get("/api/scoring-weights")
async def get_scoring_weights():
    """
    Get current scoring configuration.
    
    Returns the weights for all active dimensions and their sub-dimensions.
    Note: Multiplatform optimization (Dimension 10) is reserved for a future phase.
    
    Returns:
        dict: Scoring weights configuration
    """
    return settings.scoring_weights


@app.post("/api/audit", response_model=AuditResponse)
async def audit_url(request: AuditRequest):
    """
    Analyze a URL for LLM citability.
    
    Performs a full audit of the given URL or pasted text, evaluating it against
    the active citability dimensions defined in the SRS.
    
    Args:
        request: AuditRequest containing URL or content_text to analyze
        
    Returns:
        AuditResponse with scores, breakdown, and recommendations
        
    Raises:
        HTTPException: If URL cannot be scraped or an internal error occurs
    """
    global scraper
    start_time = time.time()
    # url is optional now, mostly for logging/referencing if provided
    url = str(request.url) if request.url else "text-mode"
    
    # Step 1: Acquisition (Scrape or use provided text)
    try:
        if request.content_text:
            # Text-only mode: Mock PageData
            text_len = len(request.content_text.split())
            page_data = PageData(
                url=request.url or "https://manual-input.local",
                final_url=request.url or "https://manual-input.local",
                html_raw=f"<html><body><h1>Analysis</h1><p>{request.content_text}</p></body></html>",
                html_rendered=f"<html><body><h1>Analysis</h1><div class='content'>{request.content_text}</div></body></html>",
                text_content=request.content_text,
                status_code=200,
                load_time_ms=0,
                word_count=text_len,
                is_ssr=True,  # Assume readable
                is_https=True, # Assume secure
                ttfb_ms=None  # Speed not evaluated in text mode
            )
        elif request.url:
            # URL mode: Playwright scraping limited by semaphore (concurrency=1)
            # and TTFB measured via independent HTTP streaming request
            async with scrape_semaphore:
                ttfb_task = measure_ttfb(request.url)
                scrape_task = scraper.scrape(request.url)
                ttfb_val, page_data = await asyncio.gather(ttfb_task, scrape_task)
                page_data.ttfb_ms = ttfb_val
        else:
            raise HTTPException(status_code=400, detail="Must provide either URL or content_text")
            
    except ScraperError as e:
        logger.warning(f"Scraper error for {request.url}: {e.reason}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to scrape URL: {e.reason}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Internal error during acquisition: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Internal error while running the audit."
        )
    
    # Step 1.5: Language Detection
    detected_lang = detect_language(page_data.text_content)
    page_data.language = detected_lang
    
    # Step 2: Run detectors
    detector_results = []
    all_recommendations = []
    
    # --- Layer 1: Technical Infrastructure (12%) ---
    # Only run for URL-based audits
    if not request.content_text:
        try:
            infra_detector = InfrastructureDetector()
            infra_result = await infra_detector.analyze(page_data)
            detector_results.append(infra_result)
            for breakdown in infra_result.breakdown:
                all_recommendations.extend(breakdown.recommendations)
        except Exception as e:
            print(f"Infrastructure detector error: {e}")

    # --- Layer 2: Metadata (10%) ---
    try:
        from src.detectors.metadata import MetadataDetector
        metadata_detector = MetadataDetector()
        metadata_result = await metadata_detector.analyze(page_data)
        detector_results.append(metadata_result)
        for breakdown in metadata_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Metadata detector error: {e}")

    # --- Layer 3: AEO Structure (18%) ---
    try:
        from src.detectors.aeo_structure import AEOStructureDetector
        aeo_detector = AEOStructureDetector()
        aeo_result = await aeo_detector.analyze(page_data)
        detector_results.append(aeo_result)
        for breakdown in aeo_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"AEO Structure detector error: {e}")

    # --- Layer 6: Entity Identification (8%) ---
    try:
        from src.detectors.entity import EntityDetector
        entity_detector = EntityDetector()
        entity_result = await entity_detector.analyze(page_data)
        detector_results.append(entity_result)
        for breakdown in entity_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Entity detector error: {e}")

    # --- Layer 4: Evidence Mapping (15%) ---
    try:
        evidence_detector = EvidenceDensityDetector()
        evidence_result = await evidence_detector.analyze(page_data)
        detector_results.append(evidence_result)
        for breakdown in evidence_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Evidence detector error: {e}")

    # --- Layer 5: E-E-A-T Authority (15%) ---
    try:
        from src.detectors.authority import AuthorityDetector
        authority_detector = AuthorityDetector()
        authority_result = await authority_detector.analyze(page_data)
        detector_results.append(authority_result)
        for breakdown in authority_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Authority detector error: {e}")

    # --- Layer 8: Formatting & UX (10%) ---
    try:
        from src.detectors.formatting import FormattingDetector
        formatting_detector = FormattingDetector()
        formatting_result = await formatting_detector.analyze(page_data)
        detector_results.append(formatting_result)
        for breakdown in formatting_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Formatting detector error: {e}")

    # --- Layer 7: Freshness (10%) ---
    try:
        from src.detectors.freshness import FreshnessDetector
        freshness_detector = FreshnessDetector()
        freshness_result = await freshness_detector.analyze(page_data)
        detector_results.append(freshness_result)
        for breakdown in freshness_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Freshness detector error: {e}")

    # --- Layer 9: Links & Verifiability (10%) ---
    try:
        from src.detectors.links import LinksDetector
        links_detector = LinksDetector()
        links_result = await links_detector.analyze(page_data)
        detector_results.append(links_result)
        for breakdown in links_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        print(f"Links detector error: {e}")

    # Note: MultiPlatformDetector (Layer 10) is reserved for future phases.
    
    # Step 3: Calculate total score and normalized contribution per dimension
    # Normalized contribution: (score * weight) / sum(active_weights)
    # This ensures that sum(r.contribution) matches total_score exactly in both URL and text mode.
    active_weights_sum = sum(r.weight for r in detector_results)
    if active_weights_sum > 0:
        for r in detector_results:
            r.contribution = (r.score * r.weight) / active_weights_sum
        total_score = sum(r.contribution for r in detector_results)
    else:
        total_score = 0.0
    
    # Step 4: Build dimension scores for response
    dimension_scores = [
        DimensionScore(
            name=r.dimension,
            score=r.score,
            weight=r.weight,
            contribution=r.contribution,
            status=r.status,
        )
        for r in detector_results
    ]
    
    # Calculate analysis time
    analysis_time_ms = (time.time() - start_time) * 1000
    
    # Single source of version from settings
    scoring_version = settings.app_version
    
    # Prioritize recommendations (show top 5)
    top_recommendations = all_recommendations[:5]
    
    return AuditResponse(
        url=url,
        total_score=total_score,
        dimensions=dimension_scores,
        scoring_version=scoring_version,
        language=detected_lang,
        analysis_time_ms=analysis_time_ms,
        analyzed_at=datetime.utcnow(),
        recommendations=top_recommendations,
        detector_results=detector_results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
