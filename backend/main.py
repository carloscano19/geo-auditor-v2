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
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from src.models.schemas import (
    AuditRequest,
    AuditResponse,
    DimensionScore,
    PageData,
    OptimizeRequest,
    OptimizeResponse,
)
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.scrapers.base_scraper import ScraperError
from src.detectors.infrastructure import InfrastructureDetector
from src.detectors.evidence_density import EvidenceDensityDetector


# Global scraper instance (reused across requests for performance)
scraper: PlaywrightScraper = None


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
    description="Sistema Avanzado de Auditoría GEO/AEO para Optimización de Citabilidad en LLMs",
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


@app.get("/api/scoring-weights")
async def get_scoring_weights():
    """
    Get current scoring configuration.
    
    Returns the weights for all 10 dimensions and their sub-dimensions.
    Useful for frontend visualization and transparency.
    
    Returns:
        dict: Scoring weights configuration
    """
    return settings.scoring_weights


@app.post("/api/audit", response_model=AuditResponse)
async def audit_url(request: AuditRequest):
    """
    Analyze a URL for LLM citability.
    
    Performs a full audit of the given URL, evaluating it against
    the 10 citability dimensions defined in the SRS.
    
    Currently implements:
    - Layer 1: Technical Infrastructure (12%)
    
    Args:
        request: AuditRequest containing URL to analyze
        
    Returns:
        AuditResponse with scores, breakdown, and recommendations
        
    Raises:
        HTTPException: If URL cannot be scraped or analyzed
    """
    global scraper
    start_time = time.time()
    # url is optional now, mostly for logging/referencing if provided
    url = str(request.url) if request.url else "text-mode"
    
    # Step 1: Acquisition (Scrape or use provided text)
    try:
        if request.content_text:
            # Text-only mode: Mock PageData
            # We construct a synthetic PageData object to feed the detectors
            text_len = len(request.content_text.split())
            page_data = PageData(
                url=request.url or "https://manual-input.local",
                final_url=request.url or "https://manual-input.local",
                html_raw=f"<html><body><h1>Analysis</h1><p>{request.content_text}</p></body></html>",
                # Wrap text in paragraphs for basic structure simulation if needed, 
                # but AEO detector works better with structure. 
                # For pure text input, AEO structure might score low on H2s unless we infer them.
                # For now, we wrap the whole text in a generic body. 
                # Ideally, the frontend should send HTML if it's a rich editor, but "Paste Text" implies plain text.
                # sophisticated text-to-html could be done here, but let's keep it simple.
                html_rendered=f"<html><body><h1>Analysis</h1><div class='content'>{request.content_text}</div></body></html>",
                text_content=request.content_text,
                status_code=200,
                load_time_ms=0,
                word_count=text_len,
                is_ssr=True,  # Assume readable
                is_https=True # Assume secure
            )
        elif request.url:
            # URL mode: Scrape
            page_data = await scraper.scrape(request.url)
        else:
            raise HTTPException(status_code=400, detail="Must provide either URL or content_text")
            
    except ScraperError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to scrape URL: {e.reason}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during acquisition: {str(e)}"
        )
    
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

    # TODO: Add remaining detectors in future phases
    # - EEATDetector (Layer 5) 
    # - FreshnessDetector (Layer 7)
    # - FormatDetector (Layer 8)
    # - LinksDetector (Layer 9)
    # - MultiPlatformDetector (Layer 10)
    
    # Step 3: Calculate total score
    total_score = sum(r.contribution for r in detector_results)
    
    # For now, scale up since we only have 1 of 10 detectors
    # This shows the infrastructure score at its full weight
    if detector_results:
        # Show the actual infrastructure contribution
        pass
    
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
    
    # Get scoring version
    scoring_version = settings.scoring_weights.get("scoring_version", "v2.0-feb2026")
    
    # Prioritize recommendations (show top 5)
    top_recommendations = all_recommendations[:5]
    
    return AuditResponse(
        url=url,
        total_score=total_score,
        dimensions=dimension_scores,
        scoring_version=scoring_version,
        analysis_time_ms=analysis_time_ms,
        analyzed_at=datetime.utcnow(),
        recommendations=top_recommendations,
        detector_results=detector_results,
    )

@app.post("/api/optimize", response_model=OptimizeResponse)
async def optimize_content(request: OptimizeRequest):
    """
    Optimize content using GenAI based on audit findings.
    """
    from src.llm_engine.service import LLMService
    llm_service = LLMService()
    
    optimized_text = await llm_service.optimize_content(
        request.content_text, 
        request.audit_results,
        request.provider,
        request.api_key
    )
    
    return OptimizeResponse(optimized_content=optimized_text)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
