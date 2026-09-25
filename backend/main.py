"""
GEO-AUDITOR AI - FastAPI Application

Main entry point for the GEO-AUDITOR AI backend.
Provides REST API endpoints for content citability auditing.

API Endpoints:
- POST /api/audit: Analyze a URL or text for LLM citability
- POST /api/batch: Start a batch audit job of up to 20 URLs
- GET /api/batch/{job_id}: Get status, progress, and topic issues of a batch job
- GET /api/batch/{job_id}/csv: Download CSV summary of a batch job
- GET /api/health: Health check endpoint
- GET /api/scoring-weights: Get current scoring configuration
"""

import io
import csv
import uuid
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from src.models.schemas import (
    AuditRequest,
    AuditResponse,
    BatchAuditRequest,
    BatchJobResponse,
    BatchItemResult,
    TopicIssue,
)
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.scrapers.base_scraper import ScraperError
import src.services.audit_service as audit_service_module
from src.services.audit_service import run_single_audit
from src.utils.batch_aggregator import aggregate_issues_by_topic

logger = logging.getLogger("geo_auditor")

async def fetch_robots_txt(url: str):
    return await audit_service_module.fetch_robots_txt(url)

async def measure_ttfb(url: str):
    return await audit_service_module.measure_ttfb(url)

# Global scraper instance (reused across requests for performance)
scraper: PlaywrightScraper = None

# Concurrency limiter: ensure only 1 Playwright scraping session runs at a time
scrape_semaphore = asyncio.Semaphore(1)

# In-memory batch job store
batch_jobs: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global scraper
    scraper = PlaywrightScraper()
    yield
    if scraper:
        await scraper.close()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Advanced GEO/AEO Audit System for LLM Citability Optimization",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/version")
async def get_version():
    """Single source of version endpoint."""
    return {
        "version": settings.app_version,
    }


@app.get("/api/scoring-weights")
async def get_scoring_weights():
    """Get current scoring configuration."""
    return settings.scoring_weights


@app.post("/api/audit", response_model=AuditResponse)
async def audit_url(request: AuditRequest):
    """
    Analyze a URL or text for LLM citability.
    """
    global scraper
    if not request.url and not request.content_text:
        raise HTTPException(status_code=400, detail="Must provide either URL or content_text")

    try:
        return await run_single_audit(
            request,
            scraper,
            scrape_semaphore,
            fetch_robots_fn=fetch_robots_txt,
            measure_ttfb_fn=measure_ttfb
        )
    except ScraperError as e:
        logger.warning(f"Scraper error for {request.url}: {e.reason}")
        raise HTTPException(status_code=400, detail=f"Failed to scrape URL: {e.reason}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Internal error during audit: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal error while running the audit.")


async def process_batch_job(job_id: str, urls: list[str], target_query: Optional[str]):
    """
    Background worker that executes audits sequentially for a batch job.
    Reuses run_single_audit and respects scrape_semaphore.
    """
    global scraper
    job = batch_jobs.get(job_id)
    if not job:
        return

    job["status"] = "running"

    for idx, raw_url in enumerate(urls):
        url = raw_url.strip()
        job["results"][idx]["status"] = "running"
        try:
            req = AuditRequest(url=url, target_query=target_query)
            audit_res = await run_single_audit(req, scraper, scrape_semaphore)
            job["results"][idx]["status"] = "done"
            job["results"][idx]["result"] = audit_res.model_dump()
            job["results"][idx]["error"] = None
        except ScraperError as e:
            logger.warning(f"Batch audit failed for {url}: {e.reason}")
            job["results"][idx]["status"] = "error"
            job["results"][idx]["error"] = f"Failed to scrape URL: {e.reason}"
        except Exception as e:
            logger.warning(f"Batch audit unexpected error for {url}: {e}")
            job["results"][idx]["status"] = "error"
            job["results"][idx]["error"] = str(e)
        finally:
            job["completed"] += 1
            # Recompute aggregated issues after each URL completes
            job["issues_by_topic"] = aggregate_issues_by_topic(job["results"])

    job["status"] = "done"


@app.post("/api/batch")
async def create_batch_audit(request: BatchAuditRequest, background_tasks: BackgroundTasks):
    """
    Initiate a batch audit for up to 20 URLs.
    """
    clean_urls = [u.strip() for u in request.urls if u and u.strip()]
    if not clean_urls:
        raise HTTPException(status_code=400, detail="URL list cannot be empty")
    if len(clean_urls) > 20:
        raise HTTPException(status_code=400, detail="A batch cannot exceed 20 URLs")

    job_id = str(uuid.uuid4())
    initial_results = [
        {"url": u, "status": "pending", "result": None, "error": None}
        for u in clean_urls
    ]

    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "total": len(clean_urls),
        "completed": 0,
        "results": initial_results,
        "issues_by_topic": [],
        "created_at": datetime.utcnow().isoformat(),
        "target_query": request.target_query,
    }

    background_tasks.add_task(process_batch_job, job_id, clean_urls, request.target_query)

    return {"job_id": job_id}


@app.get("/api/batch/{job_id}", response_model=BatchJobResponse)
async def get_batch_status(job_id: str):
    """
    Get the status and results of a batch audit job.
    """
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Batch job not found or expired. In-memory jobs are reset on server restart."
        )
    return job


@app.get("/api/batch/{job_id}/csv")
async def export_batch_csv(job_id: str):
    """
    Export batch audit results to CSV format.
    """
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Batch job not found or expired. In-memory jobs are reset on server restart."
        )

    output = io.StringIO()
    writer = csv.writer(output)

    # Collect all dimension names for header
    dimension_names = [
        "technical_infrastructure",
        "metadata_schema",
        "aeo_structure",
        "passage_quality",
        "evidence_density",
        "eeat_authority",
        "entity_identification",
        "freshness",
        "format_citability",
        "links_verifiability",
    ]
    if job.get("target_query"):
        dimension_names.append("query_match")

    headers = [
        "URL",
        "Total Score",
        "Content Type",
        "Language",
        *[d.replace("_", " ").title() for d in dimension_names],
        "Status",
        "Error",
    ]
    writer.writerow(headers)

    for item in job.get("results", []):
        url = item.get("url", "")
        status = item.get("status", "")
        error = item.get("error", "") or ""
        res = item.get("result")

        if res:
            total_score = f"{res.get('total_score', 0):.1f}"
            content_type = res.get("content_type", "")
            language = res.get("language", "")

            dim_dict = {d.get("name"): d.get("score") for d in res.get("dimensions", [])}
            dim_scores = [
                f"{dim_dict.get(d, 0):.1f}" if d in dim_dict else "N/A"
                for d in dimension_names
            ]
        else:
            total_score = "N/A"
            content_type = "N/A"
            language = "N/A"
            dim_scores = ["N/A" for _ in dimension_names]

        row = [
            url,
            total_score,
            content_type,
            language,
            *dim_scores,
            status,
            error,
        ]
        writer.writerow(row)

    output.seek(0)
    filename = f"geo_audit_batch_{job_id[:8]}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
