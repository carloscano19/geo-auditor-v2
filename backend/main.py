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
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import hashlib
from config.settings import get_settings
from src.models.schemas import (
    AuditRequest,
    AuditResponse,
    BatchAuditRequest,
    BatchJobResponse,
    BatchItemResult,
    TopicIssue,
    AIFixesRequest,
    AIFixesResponse,
    LeadParagraphFix,
)
from src.services.llm_client import (
    LLMClient,
    DailyLimitExceededError,
    LLMClientError,
)
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.scrapers.base_scraper import ScraperError, ChallengePageError
import src.services.audit_service as audit_service_module
from src.services.audit_service import run_single_audit
from src.utils.batch_aggregator import (
    aggregate_issues_by_topic,
    DIMENSION_DISPLAY_NAMES,
)

CONTENT_TYPE_DISPLAY_NAMES: Dict[str, str] = {
    "news": "News",
    "guide_blog": "Guide/Blog",
    "review": "Review",
    "product": "Product",
}

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


def cleanup_batch_jobs(max_jobs: int = 10, max_age_hours: int = 2) -> None:
    """
    In-memory batch jobs cleanup:
    1. Removes completed jobs ('done') older than max_age_hours (default 2 hours).
    2. Keeps at most max_jobs (default 10). If exceeded, removes the oldest completed jobs.
    """
    now = datetime.now(timezone.utc)

    def parse_dt(dt_val: Any) -> Optional[datetime]:
        if not dt_val:
            return None
        if isinstance(dt_val, datetime):
            return dt_val if dt_val.tzinfo else dt_val.replace(tzinfo=timezone.utc)
        try:
            dt = datetime.fromisoformat(str(dt_val))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    # 1. Remove completed jobs older than max_age_hours
    expired_ids = []
    for jid, job in list(batch_jobs.items()):
        if job.get("status") == "done":
            completed_dt = parse_dt(job.get("completed_at")) or parse_dt(job.get("created_at"))
            if completed_dt and (now - completed_dt) > timedelta(hours=max_age_hours):
                expired_ids.append(jid)

    for jid in expired_ids:
        batch_jobs.pop(jid, None)

    # 2. Keep at most max_jobs: if exceeded, prune oldest completed jobs
    if len(batch_jobs) > max_jobs:
        completed_jobs = [
            (jid, job)
            for jid, job in batch_jobs.items()
            if job.get("status") == "done"
        ]
        completed_jobs.sort(
            key=lambda item: parse_dt(item[1].get("completed_at"))
            or parse_dt(item[1].get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        while len(batch_jobs) > max_jobs and completed_jobs:
            oldest_id, _ = completed_jobs.pop(0)
            batch_jobs.pop(oldest_id, None)



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


# In-memory 24h cache for AI fixes: sha256 -> (result_dict, expires_at_timestamp)
# OrderedDict to easily evict oldest entries when max capacity is reached
from collections import OrderedDict
AI_FIXES_CACHE_MAX_SIZE = 100
ai_fixes_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()


def cleanup_ai_fixes_cache(now_ts: float):
    """Remove expired entries from ai_fixes_cache."""
    expired_keys = [k for k, v in ai_fixes_cache.items() if now_ts >= v[1]]
    for k in expired_keys:
        ai_fixes_cache.pop(k, None)


def put_ai_fixes_cache(key: str, data: dict, expires_at: float):
    """Store result in cache, cleaning expired and evicting oldest if over 100 entries."""
    now_ts = datetime.now(timezone.utc).timestamp()
    cleanup_ai_fixes_cache(now_ts)
    if key in ai_fixes_cache:
        ai_fixes_cache.pop(key, None)
    ai_fixes_cache[key] = (data, expires_at)
    while len(ai_fixes_cache) > AI_FIXES_CACHE_MAX_SIZE:
        ai_fixes_cache.popitem(last=False)



@app.get("/api/version")
async def get_version():
    """Single source of version endpoint."""
    return {
        "version": settings.app_version,
        "ai_enabled": settings.ai_enabled,
    }


@app.get("/api/scoring-weights")
async def get_scoring_weights():
    """Get current scoring configuration."""
    return settings.scoring_weights


@app.post("/api/audit", response_model=AuditResponse, response_model_exclude_none=True)
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
    except ChallengePageError as e:
        logger.warning(f"Challenge page detected for {request.url}: {e.reason}")
        raise HTTPException(status_code=400, detail=e.reason)
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


@app.post("/api/ai/fixes", response_model=AIFixesResponse)
async def generate_ai_fixes(request: AIFixesRequest):
    """
    Generate Schema.org JSON-LD and optimized lead paragraph using LLM.
    Protected by 24h cache, daily call limit, and strict field overwriting.
    """
    current_settings = get_settings()
    if not current_settings.ai_enabled:
        raise HTTPException(status_code=503, detail="AI layer is not configured")

    ctx = request.ai_context

    # 1. Check in-memory 24h cache
    cache_key_raw = f"{ctx.url or ''}::{ctx.main_text or ''}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8")).hexdigest()
    now_ts = datetime.now(timezone.utc).timestamp()

    if cache_key in ai_fixes_cache:
        cached_data, expires_at = ai_fixes_cache[cache_key]
        if now_ts < expires_at:
            return AIFixesResponse(**cached_data)
        else:
            ai_fixes_cache.pop(cache_key, None)

    # 2. Prepare LLM prompt
    expected_type = "Article"
    if ctx.content_type == "news":
        expected_type = "NewsArticle"
    elif ctx.content_type == "review":
        expected_type = "Review"
    elif ctx.content_type == "product":
        expected_type = "Product"
    elif ctx.content_type == "guide_blog":
        expected_type = "Article"

    failing_info = "\n".join([f"- {f.name}: {f.score}/100 ({f.recommendation or 'Needs improvement'})" for f in ctx.failing_submetrics])

    system_prompt = (
        "You are an expert AI Search Engine Optimization (GEO/AEO) engineer.\n"
        "Generate actionable fixes for web content to maximize citability by AI models (ChatGPT, Perplexity, Gemini).\n"
        "Return ONLY a valid JSON object matching the requested schema without conversational filler."
    )

    user_prompt = f"""Given this audited page content and its weaknesses, generate:
1. Valid Schema.org JSON-LD for @type "{expected_type}".
2. An optimized lead paragraph (40-60 words) that immediately answers the primary user intent, states the main entity in the first sentence, uses strictly facts from the provided text, and removes fluff.

Page URL: {ctx.url or 'N/A'}
Page Title: {ctx.title or 'N/A'}
Page H1: {ctx.h1 or 'N/A'}
Language: {ctx.language}
Content Type: {ctx.content_type} (Target Schema @type: {expected_type})
Detected Author: {ctx.detected_author or 'Not detected'}
Detected Date Published: {ctx.detected_date_published or 'Not detected'}
Detected Date Modified: {ctx.detected_date_modified or 'Not detected'}
Detected Publisher: {ctx.detected_publisher or 'Not detected'}

Original First Paragraph:
\"\"\"{ctx.first_paragraph or 'None'}\"\"\"

Failing Submetrics:
{failing_info or 'None'}

Main Text Snippet (First 8000 chars):
\"\"\"{ctx.main_text}\"\"\"

Return a JSON object with this exact structure:
{{
  "json_ld": {{
    "@context": "https://schema.org",
    "@type": "{expected_type}",
    "headline": "{ctx.title or ctx.h1 or 'Headline'}",
    "description": "Short summary",
    ...
  }},
  "lead_paragraph": {{
    "original": "{ctx.first_paragraph or ''}",
    "suggested": "40-60 words optimized direct-answer paragraph",
    "rationale": "Clear explanation of changes made"
  }}
}}
Rules:
- For missing fields (e.g. image, publisher logo), use uppercase placeholder like "REPLACE_WITH_IMAGE_URL".
- Do NOT invent facts or statistics not present in the text.
- Language of the suggested paragraph must match the page language ({ctx.language}).
"""

    llm = LLMClient()
    try:
        raw_result = await llm.call_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except DailyLimitExceededError as e:
        raise HTTPException(status_code=429, detail="Daily AI limit reached, try again tomorrow")
    except LLMClientError as e:
        logger.error(f"LLM fixes generation error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error calling LLM: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate AI fixes")

    # 3. Validate and enforce JSON-LD fields
    json_ld = raw_result.get("json_ld", {})
    if not isinstance(json_ld, dict):
        json_ld = {}

    # Always ensure @context is https://schema.org
    json_ld["@context"] = "https://schema.org"

    # Validate/enforce @type
    valid_types = {
        "news": ["NewsArticle"],
        "guide_blog": ["Article", "BlogPosting"],
        "review": ["Review"],
        "product": ["Product"],
    }
    allowed_types = valid_types.get(ctx.content_type, ["Article", "BlogPosting", "NewsArticle", "Review", "Product"])
    current_type = json_ld.get("@type")
    if current_type not in allowed_types:
        json_ld["@type"] = expected_type

    # Overwrite known fields with extracted ground-truth or strict placeholders to prevent hallucinations
    # 1. Headline / Name
    if ctx.content_type in ["product", "review"]:
        json_ld.pop("headline", None)
        json_ld["name"] = ctx.title or ctx.h1 or ctx.url or "REPLACE_WITH_NAME"
    else:
        json_ld["headline"] = ctx.title or ctx.h1 or ctx.url or "REPLACE_WITH_HEADLINE"

    if ctx.url:
        json_ld["url"] = ctx.url

    # 2. Date published & modified
    if ctx.detected_date_published:
        json_ld["datePublished"] = ctx.detected_date_published
    else:
        json_ld["datePublished"] = "REPLACE_WITH_DATE_PUBLISHED"

    if ctx.detected_date_modified:
        json_ld["dateModified"] = ctx.detected_date_modified
    else:
        json_ld["dateModified"] = "REPLACE_WITH_DATE_MODIFIED"

    # 3. Author
    if ctx.detected_author:
        json_ld["author"] = {"@type": "Person", "name": ctx.detected_author}
    else:
        json_ld["author"] = {"@type": "Person", "name": "REPLACE_WITH_AUTHOR_NAME"}

    # 4. Publisher
    if ctx.detected_publisher:
        json_ld["publisher"] = {"@type": "Organization", "name": ctx.detected_publisher}
    else:
        json_ld["publisher"] = {"@type": "Organization", "name": "REPLACE_WITH_PUBLISHER_NAME"}

    # Set placeholder for image if missing
    if "image" not in json_ld or not json_ld["image"]:
        json_ld["image"] = "REPLACE_WITH_IMAGE_URL"

    # Warnings collection
    warnings: list[str] = []
    if not ctx.detected_author:
        warnings.append("Author not detected on page; add author details manually in schema.")
    else:
        author_str = ctx.detected_author.strip()
        # Check if author looks like a username: no spaces AND (contains '.', '_', '-' OR is all lowercase)
        if " " not in author_str and (any(c in author_str for c in [".", "_", "-"]) or author_str.islower()):
            warnings.append(f"Detected author '{author_str}' looks like a username; replace it with the author's full name.")

    if not ctx.detected_date_published:
        warnings.append("Publication date not detected; add datePublished manually in schema.")
    if not ctx.title and not ctx.h1:
        warnings.append("Title or H1 missing; add headline manually in schema.")

    if getattr(ctx, "publisher_inferred_from_domain", False):
        warnings.append("Publisher name inferred from domain; confirm the official organization name.")

    # 4. Lead paragraph validation
    lead_data = raw_result.get("lead_paragraph", {})
    original_lead = (ctx.first_paragraph or "").strip()
    suggested_lead = lead_data.get("suggested", "").strip() if isinstance(lead_data, dict) else ""
    rationale_lead = lead_data.get("rationale", "").strip() if isinstance(lead_data, dict) else ""

    if not suggested_lead:
        suggested_lead = original_lead or "No lead paragraph available."
    if not rationale_lead:
        rationale_lead = "Optimized for directness, inverted pyramid structure, and entity clarity."

    lead_paragraph_fix = LeadParagraphFix(
        original=original_lead,
        suggested=suggested_lead,
        rationale=rationale_lead,
    )

    response_data = {
        "json_ld": json_ld,
        "lead_paragraph": lead_paragraph_fix.model_dump(),
        "warnings": warnings,
    }

    # 5. Store in 24h cache (86400 seconds) with max 100 entries & cleanup
    put_ai_fixes_cache(cache_key, response_data, now_ts + 86400)

    return AIFixesResponse(**response_data)



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
        except ChallengePageError as e:
            logger.warning(f"Batch audit challenge detected for {url}: {e.reason}")
            job["results"][idx]["status"] = "error"
            job["results"][idx]["error"] = e.reason
            job["results"][idx]["result"] = None
        except ScraperError as e:
            logger.warning(f"Batch audit failed for {url}: {e.reason}")
            job["results"][idx]["status"] = "error"
            job["results"][idx]["error"] = f"Failed to scrape URL: {e.reason}"
            job["results"][idx]["result"] = None
        except Exception as e:
            logger.error(f"Unexpected error during batch audit of {url}: {traceback.format_exc()}")
            job["results"][idx]["status"] = "error"
            job["results"][idx]["error"] = "Internal error while auditing this URL."
            job["results"][idx]["result"] = None
        finally:
            job["completed"] += 1
            # Recompute aggregated issues after each URL completes
            page_issues, site_wide = aggregate_issues_by_topic(job["results"])
            job["issues_by_topic"] = page_issues
            job["site_wide_issues"] = site_wide

    job["status"] = "done"
    job["completed_at"] = datetime.now(timezone.utc).isoformat()


@app.post("/api/batch")
async def create_batch_audit(request: BatchAuditRequest, background_tasks: BackgroundTasks):
    """
    Initiate a batch audit for up to 20 URLs.
    """
    # 1. Clean up expired (>2 hours) and excess (>10) completed jobs
    cleanup_batch_jobs()

    # 2. Limit active batch audits: max 2 pending or running
    active_jobs = sum(1 for j in batch_jobs.values() if j.get("status") in ("pending", "running"))
    if active_jobs >= 2:
        raise HTTPException(
            status_code=429,
            detail="Too many batch audits running. Please try again in a few minutes."
        )

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
        "site_wide_issues": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "target_query": request.target_query,
    }

    # Ensure max 10 jobs constraint is preserved after adding new job
    cleanup_batch_jobs()

    background_tasks.add_task(process_batch_job, job_id, clean_urls, request.target_query)

    return {"job_id": job_id}


@app.get("/api/batch/{job_id}", response_model=BatchJobResponse)
async def get_batch_status(job_id: str):
    """
    Get the status and results of a batch audit job.
    """
    cleanup_batch_jobs()
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
    Export batch audit results to CSV format with UTF-8 BOM.
    """
    cleanup_batch_jobs()
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
        *[DIMENSION_DISPLAY_NAMES.get(d, d.replace("_", " ").title()) for d in dimension_names],
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
            raw_content_type = res.get("content_type", "")
            content_type = CONTENT_TYPE_DISPLAY_NAMES.get(raw_content_type, raw_content_type.title())
            language = (res.get("language") or "").upper()

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

    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"geo_audit_batch_{job_id[:8]}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/batch/{job_id}/issues.csv")
async def export_batch_issues_csv(job_id: str):
    """
    Export batch audit aggregated issues to CSV format with UTF-8 BOM.
    Columns: Priority, Scope, Topic, Dimension, Pages affected, Impact, Recommendation, Affected URLs
    """
    cleanup_batch_jobs()
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Batch job not found or expired. In-memory jobs are reset on server restart."
        )

    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        "Priority",
        "Scope",
        "Topic",
        "Dimension",
        "Pages affected",
        "Impact",
        "Recommendation",
        "Affected URLs",
    ]
    writer.writerow(headers)

    def format_issue_recommendations(issue_data: dict) -> str:
        breakdown = issue_data.get("recommendation_breakdown", [])
        if not breakdown:
            return issue_data.get("top_recommendation", "") or ""
        if len(breakdown) == 1:
            return breakdown[0].get("recommendation", "")
        return " | ".join(
            f"{item['recommendation']} ({item['page_count']} page{'s' if item['page_count'] != 1 else ''})"
            for item in breakdown
            if item.get("recommendation")
        )

    priority = 1
    # 1. Site-wide issues first
    for issue in job.get("site_wide_issues", []):
        dim_key = issue.get("dimension", "")
        dim_label = DIMENSION_DISPLAY_NAMES.get(dim_key, dim_key)
        urls_joined = " | ".join(issue.get("affected_urls", []))
        impact_val = f"{issue.get('impact', 0.0):.2f}"
        domain = issue.get("domain", "")
        scope_str = f"Site-wide ({domain})" if domain else "Site-wide"

        writer.writerow([
            priority,
            scope_str,
            issue.get("submetric", ""),
            dim_label,
            issue.get("affected_count", 0),
            impact_val,
            format_issue_recommendations(issue),
            urls_joined,
        ])
        priority += 1

    # 2. Page-level issues next
    for issue in job.get("issues_by_topic", []):
        dim_key = issue.get("dimension", "")
        dim_label = DIMENSION_DISPLAY_NAMES.get(dim_key, dim_key)
        urls_joined = " | ".join(issue.get("affected_urls", []))
        impact_val = f"{issue.get('impact', 0.0):.2f}"

        writer.writerow([
            priority,
            "Page",
            issue.get("submetric", ""),
            dim_label,
            issue.get("affected_count", 0),
            impact_val,
            format_issue_recommendations(issue),
            urls_joined,
        ])
        priority += 1

    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"geo_audit_issues_{job_id[:8]}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
