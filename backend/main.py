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
import re
import uuid
import asyncio
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
import time
import hmac
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import hashlib
from config.settings import get_settings
from urllib.parse import urlparse
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
    AIPlanRequest,
    AIPlanResponse,
    PlanQuestion,
    PlanOutlineItem,
    PlanTable,
    PlanDataOpportunity,
    PlanNewParagraph,
    PlanInconsistency,
    PlanSourceToCite,
)
from src.services.llm_client import (
    LLMClient,
    DailyLimitExceededError,
    LLMClientError,
)
from src.services.serp_client import (
    SerpClient,
    SerpClientError,
    SerpDailyLimitExceededError,
    get_market_for_language,
)
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.scrapers.base_scraper import ScraperError, ChallengePageError
import src.services.audit_service as audit_service_module
from src.services.audit_service import run_single_audit
from src.utils.batch_aggregator import (
    aggregate_issues_by_topic,
    DIMENSION_DISPLAY_NAMES,
)
from src.utils.lang_patterns import (
    TECHNICAL_DATA_OPP_PHRASES,
    MISSING_INFO_ANSWER_PHRASES,
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

failed_auth_attempts: dict[str, list[float]] = {}


def reset_failed_auth_attempts():
    """Reset failed auth attempts for tests."""
    failed_auth_attempts.clear()


@app.middleware("http")
async def access_code_middleware(request: Request, call_next):
    # Allow CORS preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    # Health and version are exempt (needed by keep-alive and login screen)
    if path in ["/api/health", "/api/version"]:
        return await call_next(request)

    current_settings = settings if (settings is not None and settings.access_required) else get_settings()
    if not current_settings.access_required:
        return await call_next(request)

    # Determine client IP
    client_ip = "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client and request.client.host:
        client_ip = request.client.host

    now = time.time()
    recent_failures = [t for t in failed_auth_attempts.get(client_ip, []) if now - t < 900.0]
    failed_auth_attempts[client_ip] = recent_failures

    # Freno a intentos fallidos: más de 10 códigos incorrectos desde la misma IP en 15 minutos -> 429
    if len(recent_failures) > 10:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many attempts, try again later"}
        )

    header_code = request.headers.get("X-Access-Code")
    if not header_code:
        return JSONResponse(
            status_code=401,
            content={"detail": "Access code required"}
        )

    expected_code = current_settings.access_code
    if not hmac.compare_digest(header_code.encode("utf-8"), expected_code.encode("utf-8")):
        recent_failures.append(now)
        failed_auth_attempts[client_ip] = recent_failures
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid access code"}
        )

    return await call_next(request)


# CORSMiddleware must be the outermost middleware so CORS headers
# (e.g. access-control-allow-origin) are added to all responses,
# including 401 and 429 errors from access_code_middleware.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/check")
async def check_access_code():
    """Verify access code validity."""
    return {"status": "ok"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
    }


# In-memory 24h caches for AI fixes and plan: sha256 -> (result_dict, expires_at_timestamp)
# OrderedDict to easily evict oldest entries when max capacity is reached
from collections import OrderedDict
AI_FIXES_CACHE_MAX_SIZE = 100
ai_fixes_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()

AI_PLAN_CACHE_MAX_SIZE = 100
ai_plan_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()


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


def cleanup_ai_plan_cache(now_ts: float):
    """Remove expired entries from ai_plan_cache."""
    expired_keys = [k for k, v in ai_plan_cache.items() if now_ts >= v[1]]
    for k in expired_keys:
        ai_plan_cache.pop(k, None)


def put_ai_plan_cache(key: str, data: dict, expires_at: float):
    """Store result in cache, cleaning expired and evicting oldest if over 100 entries."""
    now_ts = datetime.now(timezone.utc).timestamp()
    cleanup_ai_plan_cache(now_ts)
    if key in ai_plan_cache:
        ai_plan_cache.pop(key, None)
    ai_plan_cache[key] = (data, expires_at)
    while len(ai_plan_cache) > AI_PLAN_CACHE_MAX_SIZE:
        ai_plan_cache.popitem(last=False)


def compute_clean_headline(ctx: Any) -> str:
    """
    Computes headline / name:
    Uses H1 if present; otherwise title without site suffix (after ' - ', ' | ', ' – ', ' · '
    when matching publisher or domain). Max 110 characters without breaking words.
    """
    candidate = ""
    if ctx.h1 and ctx.h1.strip():
        candidate = ctx.h1.strip()
    elif ctx.title and ctx.title.strip():
        candidate = ctx.title.strip()
        domain = ""
        if ctx.url:
            try:
                domain = urlparse(ctx.url).netloc.lower().replace("www.", "")
            except Exception:
                pass
        pub = (ctx.detected_publisher or "").strip().lower()

        for sep in [" - ", " | ", " – ", " · "]:
            if sep in candidate:
                parts = candidate.rsplit(sep, 1)
                prefix = parts[0].strip()
                suffix = parts[1].strip().lower()
                matches_pub = bool(pub and (suffix == pub or pub in suffix or suffix in pub))
                matches_dom = bool(domain and (suffix == domain or domain in suffix or suffix in domain))
                # If matches pub/domain or suffix looks like a brand/site name (short or contains dot)
                if matches_pub or matches_dom or len(suffix.split()) <= 4:
                    candidate = prefix
                    break

    if not candidate:
        candidate = ctx.url or "REPLACE_WITH_HEADLINE"

    # Truncate to max 110 chars without breaking words
    if len(candidate) > 110:
        cut = candidate[:111]
        last_space = cut.rfind(" ")
        if last_space > 0:
            candidate = candidate[:last_space].strip()
        else:
            candidate = candidate[:110].strip()

    return candidate


def is_organization_author(author: str, publisher: Optional[str], url: Optional[str]) -> bool:
    """
    Checks if author is an organization: matches publisher case-insensitively,
    has domain or brand format (contains common TLDs), or matches URL domain.
    """
    if not author:
        return False
    a_lower = author.strip().lower()
    
    # 1. Matches publisher case-insensitively
    if publisher and a_lower == publisher.strip().lower():
        return True
        
    # 2. Matches URL domain
    if url:
        try:
            dom = urlparse(url).netloc.lower().replace("www.", "")
            if a_lower == dom or a_lower.replace("www.", "") == dom:
                return True
        except Exception:
            pass

    # 3. Has domain or brand format (contains common TLDs like .com, .io, .net, etc.)
    if re.search(r'\.(?:com|io|net|org|es|co|info|biz|me|ai|app|dev|xyz|eu|tv|agency|store)\b', a_lower):
        return True

    return False


def build_article_schema(ctx: Any, expected_type: str, json_ld_template: Optional[dict] = None) -> tuple[dict, list[str]]:
    """
    Builds and enforces schema fields for Article/NewsArticle/Product/Review.
    Applies ground truth overwriting, placeholder substitution, and warning generation.
    """
    json_ld = dict(json_ld_template or {})
    json_ld["@context"] = "https://schema.org"

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

    # 1. Headline / Name
    clean_h = compute_clean_headline(ctx)
    if ctx.content_type in ["product", "review"]:
        json_ld.pop("headline", None)
        json_ld["name"] = clean_h
    else:
        json_ld["headline"] = clean_h

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

    # 3. Author & Organization author check
    warnings: list[str] = []
    author_str = (ctx.detected_author or "").strip()
    if not author_str:
        json_ld["author"] = {"@type": "Person", "name": "REPLACE_WITH_AUTHOR_NAME"}
        warnings.append("Author not detected on page; add author details manually in schema.")
    else:
        if is_organization_author(author_str, ctx.detected_publisher, ctx.url):
            json_ld["author"] = {"@type": "Organization", "name": author_str}
            warnings.append("The author is the organization itself; add a named person as author if the page has one.")
        else:
            json_ld["author"] = {"@type": "Person", "name": author_str}
            # Username check: no spaces AND (contains '.', '_', '-' OR is all lowercase)
            if " " not in author_str and (any(c in author_str for c in [".", "_", "-"]) or author_str.islower()):
                warnings.append(f"Detected author '{author_str}' looks like a username; replace it with the author's full name.")

    # 4. Publisher
    if ctx.detected_publisher:
        json_ld["publisher"] = {"@type": "Organization", "name": ctx.detected_publisher}
    else:
        json_ld["publisher"] = {"@type": "Organization", "name": "REPLACE_WITH_PUBLISHER_NAME"}

    # 5. Image
    if getattr(ctx, "detected_image_url", None):
        json_ld["image"] = ctx.detected_image_url
    else:
        json_ld["image"] = "REPLACE_WITH_IMAGE_URL"

    # Warnings collection
    if not ctx.detected_date_published:
        warnings.append("Publication date not detected; add datePublished manually in schema.")
    if not ctx.title and not ctx.h1:
        warnings.append("Title or H1 missing; add headline manually in schema.")

    if getattr(ctx, "publisher_inferred_from_domain", False):
        warnings.append("Publisher name inferred from domain; confirm the official organization name.")

    return json_ld, warnings


def build_combined_schema(ctx: Any, article_schema: dict, questions: list[dict]) -> dict:
    """
    Constructs a JSON-LD @graph containing the article, FAQPage (only for 'page' questions),
    and Organization publisher.
    """
    page_questions = [q for q in questions if q.get("answer_source") == "page"]
    faq_schema = {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q.get("question", ""),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": q.get("draft_answer", "")
                }
            }
            for q in page_questions
        ]
    }
    
    pub_name = ctx.detected_publisher or "REPLACE_WITH_PUBLISHER_NAME"
    org_schema = {
        "@type": "Organization",
        "name": pub_name
    }
    if ctx.url:
        try:
            parsed = urlparse(ctx.url)
            org_schema["url"] = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass

    article_obj = dict(article_schema)
    article_obj.pop("@context", None)

    return {
        "@context": "https://schema.org",
        "@graph": [
            article_obj,
            faq_schema,
            org_schema
        ]
    }


def normalize_text_for_numbers(text: str) -> str:
    """Normalizes currency, multipliers, percentages, and separators for numerical comparison."""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r'[\$€£¥]', '', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:bn|b)(?!illion)\b', r'\1 billion', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:mil\s+millones)\b', r'\1 billion', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:m)(?!illion)\b', r'\1 million', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:millones)\b', r'\1 million', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:k)(?!housand)\b', r'\1 thousand', t)
    t = re.sub(r'\b(\d+(?:[\.,]\d+)?)\s*(?:mil)\b', r'\1 thousand', t)
    t = re.sub(r'(\d+)\s*(?:%|por\s*ciento)', r'\1 percent', t)
    t = re.sub(r'\b(\d{1,3})[,\.](\d{3})\b', r'\1\2', t)
    return t


def extract_numbers_with_context(text: str) -> list[str]:
    """Extracts all numerical expressions from text."""
    norm = normalize_text_for_numbers(text)
    matches = re.findall(r'\b\d+(?:[\.,]\d+)?(?:\s+(?:billion|million|thousand|trillion|percent))?\b', norm)
    return [m.strip() for m in matches if m.strip()]


def all_numbers_in_page(text: str, page_norm: str) -> bool:
    """Returns True if every number in text is found in page_norm."""
    tokens = extract_numbers_with_context(text)
    for tok in tokens:
        escaped = re.escape(tok)
        if not re.search(r'(?<!\d)' + escaped + r'(?!\d)', page_norm):
            return False
    return True


def strip_urls(text: str) -> str:
    """Removes all URLs from text."""
    if not text:
        return ""
    t = re.sub(r'https?://[^\s]+', '', text)
    return re.sub(r'\s+', ' ', t).strip()


def remove_verification_phrases(text: str) -> str:
    """
    Removes sentences containing editorial verification instructions:
    'should be verified', 'should be checked', 'needs to be verified', 'must be verified',
    'debería verificarse', 'habría que comprobar'.
    Leaves standalone 'verify' intact.
    """
    if not text:
        return ""
    pattern = re.compile(
        r'\b(should be verified|should be checked|needs to be verified|must be verified|debería verificarse|deberia verificarse|habría que comprobar|habria que comprobar)\b',
        re.IGNORECASE
    )
    # Split into sentences preserving punctuation or delimiters
    raw_sentences = re.split(r'([.!?]+(?:\s+|$))', text)
    cleaned_chunks: list[str] = []
    
    # Reconstruct sentences in pairs: (sentence_content, punctuation)
    idx = 0
    while idx < len(raw_sentences):
        sent = raw_sentences[idx]
        punct = raw_sentences[idx + 1] if idx + 1 < len(raw_sentences) else ""
        idx += 2
        
        full_sent = sent + punct
        if not pattern.search(full_sent):
            cleaned_chunks.append(full_sent)
            
    result = "".join(cleaned_chunks)
    return re.sub(r'\s+', ' ', result).strip()


def remove_financial_advice_phrases(text: str) -> str:
    """
    Removes sentences containing investment advice / call to action:
    'investors should', 'you should invest', 'consider investing',
    'los inversores deberían' / 'deberian', 'deberías invertir' / 'deberias invertir'.
    """
    if not text:
        return ""
    pattern = re.compile(
        r'\b(investors should|you should invest|consider investing|los inversores deberían|los inversores deberian|deberías invertir|deberias invertir)\b',
        re.IGNORECASE
    )
    raw_sentences = re.split(r'([.!?]+(?:\s+|$))', text)
    cleaned_chunks: list[str] = []
    
    idx = 0
    while idx < len(raw_sentences):
        sent = raw_sentences[idx]
        punct = raw_sentences[idx + 1] if idx + 1 < len(raw_sentences) else ""
        idx += 2
        
        full_sent = sent + punct
        if not pattern.search(full_sent):
            cleaned_chunks.append(full_sent)
            
    result = "".join(cleaned_chunks)
    return re.sub(r'\s+', ' ', result).strip()


def normalize_for_paa_match(text: str) -> str:
    """Normalize text for PAA matching by removing accents/diacritics, punctuation, extra spaces, and lowercasing."""
    if not text:
        return ""
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    clean = re.sub(r"[^\w\s]", "", without_accents).lower()
    return re.sub(r"\s+", " ", clean).strip()


async def resolve_serp_query(
    ctx: Any,
    llm: LLMClient,
    request_target_query: Optional[str] = None
) -> str:
    """
    Resolve the primary search query for SERP data:
    1. If user provided Target query, use that.
    2. Otherwise, make a short LLM call returning {"query": "..."} (2-6 words in page language).
    3. If LLM call fails, fallback to H1 (or Title) truncated to 8 words.
    """
    tq = (request_target_query or getattr(ctx, "target_query", None) or "").strip()
    if tq:
        return tq

    lang = getattr(ctx, "language", "en") or "en"
    lang_name = "Spanish" if lang.startswith("es") else "English"
    prompt = (
        f"Given this page title, H1, and content snippet, return the primary search query "
        f"(2-6 words, in {lang_name}) that a user would type into Google to find this page.\n"
        f"Page Title: {getattr(ctx, 'title', None) or 'N/A'}\n"
        f"Page H1: {getattr(ctx, 'h1', None) or 'N/A'}\n"
        f"Snippet: {getattr(ctx, 'main_text', '')[:1000] if getattr(ctx, 'main_text', '') else 'N/A'}\n\n"
        f'Return ONLY a valid JSON object: {{"query": "primary search query"}}'
    )
    try:
        res = await llm.call_chat_completion(
            messages=[
                {"role": "system", "content": "You are an SEO keyword specialist. Return ONLY a JSON object with the requested key."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        if isinstance(res, dict) and res.get("query") and isinstance(res["query"], str):
            q_clean = res["query"].strip()
            if q_clean:
                return q_clean
    except Exception as e:
        logger.warning(f"Short LLM query generation failed: {e}")

    fallback_text = (getattr(ctx, "h1", None) or getattr(ctx, "title", None) or "guide").strip()
    words = fallback_text.split()
    return " ".join(words[:8])


@app.get("/api/version")
async def get_version():
    """Single source of version endpoint."""
    s = settings if (settings is not None and (settings.ai_enabled or settings.serp_enabled or settings.access_required)) else get_settings()
    return {
        "version": s.app_version,
        "ai_enabled": s.ai_enabled,
        "serp_enabled": s.serp_enabled,
        "access_required": s.access_required,
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
- In financial, investment, or regulated topics, do NOT give investment advice, recommendations, or calls to action to investors; strictly describe what the page says.
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

    # 3. Validate and enforce JSON-LD fields using build_article_schema
    json_ld_raw = raw_result.get("json_ld", {})
    if not isinstance(json_ld_raw, dict):
        json_ld_raw = {}

    json_ld, warnings = build_article_schema(ctx, expected_type, json_ld_raw)

    page_norm = normalize_text_for_numbers(ctx.main_text or "")
    removed_fixes_count = 0

    # 3.1 Validate numeric figures in LLM-generated JSON-LD text fields
    for field in ["description", "alternativeHeadline"]:
        if field in json_ld and isinstance(json_ld[field], str) and json_ld[field]:
            if not all_numbers_in_page(json_ld[field], page_norm):
                del json_ld[field]
                removed_fixes_count += 1

    for field in ["about", "mentions"]:
        if field in json_ld:
            val = json_ld[field]
            if isinstance(val, list):
                valid_items = []
                for item in val:
                    if isinstance(item, dict):
                        item_ok = True
                        for k in ["name", "description"]:
                            if k in item and isinstance(item[k], str) and item[k]:
                                if not all_numbers_in_page(item[k], page_norm):
                                    item_ok = False
                                    break
                        if item_ok:
                            valid_items.append(item)
                        else:
                            removed_fixes_count += 1
                    elif isinstance(item, str):
                        if all_numbers_in_page(item, page_norm):
                            valid_items.append(item)
                        else:
                            removed_fixes_count += 1
                json_ld[field] = valid_items
            elif isinstance(val, dict):
                item_ok = True
                for k in ["name", "description"]:
                    if k in val and isinstance(val[k], str) and val[k]:
                        if not all_numbers_in_page(val[k], page_norm):
                            item_ok = False
                            break
                if not item_ok:
                    del json_ld[field]
                    removed_fixes_count += 1

    if removed_fixes_count > 0:
        warnings.append(
            f"{removed_fixes_count} Schema.org elements were removed because they contained figures not found on the page."
        )

    # 4. Lead paragraph validation & numeric check
    lead_data = raw_result.get("lead_paragraph", {})
    original_lead = (ctx.first_paragraph or "").strip()
    suggested_lead = lead_data.get("suggested", "").strip() if isinstance(lead_data, dict) else ""
    rationale_lead = lead_data.get("rationale", "").strip() if isinstance(lead_data, dict) else ""

    if suggested_lead:
        suggested_lead = remove_financial_advice_phrases(suggested_lead)

    if suggested_lead and not all_numbers_in_page(suggested_lead, page_norm):
        suggested_lead = original_lead
        rationale_lead = "The original lead paragraph was kept because the suggested lead contained unverified figures."
        warnings.append("The suggested lead contained figures not found on the page and was discarded.")

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


@app.post("/api/ai/plan", response_model=AIPlanResponse)
async def generate_ai_plan(request: AIPlanRequest):
    """
    Generate complete AI improvement plan for the audited page.
    Includes questions to answer, suggested H2 structure, suggested table,
    enriching data opportunities, actionable new paragraphs, sources to cite, and combined Schema.org.
    """
    current_settings = get_settings()
    if not current_settings.ai_enabled:
        raise HTTPException(status_code=503, detail="AI layer is not configured")

    ctx = request.ai_context

    # 1. Check in-memory 24h cache
    cache_key_raw = f"plan::{ctx.url or ''}::{ctx.main_text or ''}::{request.target_query or ctx.target_query or ''}::{current_settings.serp_enabled}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8")).hexdigest()
    now_ts = datetime.now(timezone.utc).timestamp()

    if cache_key in ai_plan_cache:
        cached_data, expires_at = ai_plan_cache[cache_key]
        if now_ts < expires_at:
            return AIPlanResponse(**cached_data)
        else:
            ai_plan_cache.pop(cache_key, None)

    llm = LLMClient()

    # 2. SERP Data via DataForSEO (if serp_enabled)
    serp_query: Optional[str] = None
    serp_market: Optional[str] = None
    serp_used = False
    serp_data: Optional[dict] = None
    candidate_sources: list[dict] = []
    warnings: list[str] = []

    if current_settings.serp_enabled:
        try:
            serp_query = await resolve_serp_query(ctx, llm, request.target_query)
            _, _, default_market = get_market_for_language(ctx.language or "en")
            serp_market = default_market
            serp_client = SerpClient()
            serp_data = await serp_client.fetch_serp_live(
                query=serp_query,
                language=ctx.language or "en",
                audited_url=ctx.url or "",
            )
            serp_used = True
            serp_market = serp_data.get("market") or default_market

            # Build candidate sources (max 8, AI Overview first, then Organic top 10, no duplicate domains)
            seen_domains = set()
            for src in serp_data.get("ai_overview_sources", []):
                dom = (src.get("domain") or "").lower().strip()
                if dom and dom not in seen_domains:
                    seen_domains.add(dom)
                    candidate_sources.append({
                        "url": src["url"],
                        "title": src.get("title") or dom,
                        "domain": dom,
                        "found_in": "AI Overview",
                    })
                if len(candidate_sources) >= 8:
                    break

            if len(candidate_sources) < 8:
                for src in serp_data.get("organic", []):
                    dom = (src.get("domain") or "").lower().strip()
                    if dom and dom not in seen_domains:
                        seen_domains.add(dom)
                        candidate_sources.append({
                            "url": src["url"],
                            "title": src.get("title") or dom,
                            "domain": dom,
                            "found_in": "Organic top 10",
                        })
                    if len(candidate_sources) >= 8:
                        break
        except SerpDailyLimitExceededError as e:
            logger.warning(f"DataForSEO daily limit reached: {e}")
            serp_used = False
            serp_data = None
            _, _, serp_market = get_market_for_language(ctx.language or "en")
            warnings.append("Daily Google data limit reached; questions and sources are AI-suggested only.")
        except SerpClientError as e:
            logger.warning(f"DataForSEO error: {e}")
            serp_used = False
            serp_data = None
            _, _, serp_market = get_market_for_language(ctx.language or "en")
            warnings.append("Google data unavailable for this plan; questions and sources are AI-suggested only.")
        except Exception as e:
            logger.warning(f"Unexpected DataForSEO error: {e}")
            serp_used = False
            serp_data = None
            _, _, serp_market = get_market_for_language(ctx.language or "en")
            warnings.append("Google data unavailable for this plan; questions and sources are AI-suggested only.")

    serp_paa_found = 0
    if serp_used and serp_data:
        serp_paa_found = len(serp_data.get("people_also_ask") or [])

    # 3. Build system and user prompt
    lang = ctx.language or "es"
    lang_instruction = "Spanish (Español)" if lang == "es" else "English"

    expected_type = "Article"
    if ctx.content_type == "news":
        expected_type = "NewsArticle"
    elif ctx.content_type == "review":
        expected_type = "Review"
    elif ctx.content_type == "product":
        expected_type = "Product"

    failing_info = "\n".join([f"- {f.name}: {f.score}/100 ({f.recommendation or 'Needs improvement'})" for f in ctx.failing_submetrics])

    system_prompt = (
        "You are an expert AI Search Engine Optimization (GEO/AEO) engineer.\n"
        "Generate a thorough, practical, and highly citability-focused content improvement plan.\n"
        f"CRITICAL: All generated suggestions and text MUST BE in {lang_instruction}.\n"
        "STRICT TRUTHFULNESS & RESTRAINT RULES:\n"
        "1. NEVER invent any statistics, figures, percentages, dates, names, or URLs.\n"
        "2. Any suggested text or draft answer containing numbers MUST ONLY use figures already explicitly present in the provided page text.\n"
        "3. If suggesting new data opportunities, describe the metric and the type of source to consult (e.g. 'official statistics', 'annual report'), but DO NOT make up URLs or numbers.\n"
        "4. In financial, investment, or regulated topics, do NOT give investment advice, recommendations, or calls to action to investors; strictly describe what the page says.\n"
        "5. Return ONLY a valid JSON object matching the requested schema without markdown quotes or conversational text.\n"
        "6. In 'data_opportunities', suggest factual data, statistics, and domain benchmarks only. DO NOT suggest technical SEO fixes (no schema, no structured data, no alt text, no metadata, no speed, no internal links)."
    )

    google_context_text = ""
    if serp_used and serp_data:
        paa_items = serp_data.get("people_also_ask", [])
        rel_items = serp_data.get("related_searches", [])
        parts = []
        if paa_items:
            paa_lines = "\n".join([f"- {p['question']}" for p in paa_items])
            parts.append(f"Google 'People Also Ask' Questions for '{serp_query}':\n{paa_lines}\n* INSTRUCTION: Prioritize these real questions in your 'questions_to_answer'. Formulate matching questions closely.")
        if rel_items:
            rel_lines = "\n".join([f"- {r}" for r in rel_items])
            parts.append(f"Google 'Related Searches' for '{serp_query}':\n{rel_lines}\n* INSTRUCTION: Use these related searches as inspiration for the 'suggested_h2_structure'.")
        if candidate_sources:
            src_lines = "\n".join([f"{i}. [{s['found_in']}] Domain: {s['domain']}, Title: {s['title']}" for i, s in enumerate(candidate_sources, start=1)])
            parts.append(f"Candidate Sources Found on Google for '{serp_query}':\n{src_lines}\n* INSTRUCTION: For each candidate source (1 to {len(candidate_sources)}), return in 'sources_why' a concise 'why' sentence in {lang_instruction} explaining why or how this audited page should cite/link to it. Do NOT return any URLs.")
        if parts:
            google_context_text = "\n\nReal Google Search Data (from DataForSEO):\n" + "\n\n".join(parts) + "\n"

    sources_why_schema = ""
    if candidate_sources:
        sources_why_schema = """,
  "sources_why": [
    {{
      "index": 1,
      "why": "Concise sentence explaining why this page should reference or cite this source"
    }}
  ]"""

    user_prompt = f"""Generate an improvement plan for the following web page to optimize its citability in AI engines (ChatGPT, Perplexity, Gemini).

Page Information:
URL: {ctx.url or 'N/A'}
Title: {ctx.title or 'N/A'}
H1: {ctx.h1 or 'N/A'}
Language: {lang}
Content Type: {ctx.content_type}
Detected Author: {ctx.detected_author or 'Not detected'}
Detected Publisher: {ctx.detected_publisher or 'Not detected'}
Detected Date Published: {ctx.detected_date_published or 'Not detected'}
Detected Date Modified: {ctx.detected_date_modified or 'Not detected'}

Failing Submetrics:
{failing_info or 'None'}

Main Text Snippet (First 8000 chars):
\"\"\"{ctx.main_text}\"\"\"{google_context_text}

Generate a JSON object with EXACTLY this structure:
{{
  "questions_to_answer": [
    {{
      "question": "Question text in {lang_instruction}",
      "draft_answer": "Direct answer (max 60 words). If answer_source is 'page', must only use facts from page text.",
      "answer_source": "page" // ONLY if the page actually answers the question directly. If the answer acknowledges or states that the page does not provide that information, answer_source MUST be 'needs_info'
    }}
  ],
  "suggested_h2_structure": [
    {{
      "h2": "Suggested or preserved H2 heading text in {lang_instruction}",
      "purpose": "Brief explanation of user intent / AEO goal",
      "status": "existing" // OR "new"
    }}
  ],
  "suggested_table": {{
    "title": "Title of the table in {lang_instruction}",
    "headers": ["Col 1", "Col 2", "Col 3"],
    "rows": [
      ["Val 1", "Val 2", "Val 3"]
    ],
    "table_idea": "Optional idea if text lacks comparative data for a full table"
  }},
  "data_opportunities": [
    {{
      "suggestion": "Description of data/metric to add in {lang_instruction} (factual/content data only; NO technical suggestions like schema, alt text, metadata, speed, or internal links)",
      "source_type": "official statistics / industry benchmark / survey / financial report"
    }}
  ],
  "paragraphs_to_add": [
    {{
      "target_issue": "Name of the problem being fixed (e.g. Missing direct answer, Missing author context, Thin content)",
      "suggested_text": "Actionable paragraph (40-80 words) ready to insert into the page. Ready-to-publish text only, with NO editor notes, NO verification requests, and NO bracketed placeholders.",
      "placement": "Where to place this paragraph (e.g. Under H2 '...', After intro)"
    }}
  ],
  "inconsistencies": [
    {{
      "issue": "Brief sentence explaining the contradiction found on the page",
      "values": ["Exact value/phrase 1 from page", "Exact value/phrase 2 from page"],
      "suggestion": "How to reconcile or unify them consistently"
    }}
  ]{sources_why_schema}
}}

Requirements:
- questions_to_answer: 3 to 6 questions. Formulate direct, user-focused questions. Prioritize real Google 'People Also Ask' questions if provided. Set answer_source to 'page' ONLY if the page actually answers the question directly; if the answer acknowledges or states that the page does not provide that information, answer_source MUST be 'needs_info'.
- suggested_h2_structure: Logical H2 structure covering main aspects. Max 7 items.
- suggested_table: If the content has comparative/structured elements, provide 2-4 rows. If the page lacks enough comparative data to build 2 rows reliably without inventing numbers, provide null for headers/rows and give 'table_idea'.
- data_opportunities: 2 to 5 suggestions of data points or factual metrics to strengthen the content. Factual and content data only. PROHIBITED: Do NOT suggest technical SEO fixes (no schema, no structured data, no alt text, no metadata, no speed, no internal links).
- paragraphs_to_add: 1 to 3 paragraphs ready to publish without editor notes or verification comments.
- inconsistencies: 0 to 3 internal contradictions found on the page (different figures, dates, or names for the same thing). The conflicting values MUST appear literally in the page text snippet. If none are found, return an empty array [].
- In financial, investment, or regulated topics, do NOT give investment advice, recommendations, or calls to action to investors; strictly describe what the page says.
- Language: Strictly {lang_instruction}.
"""

    try:
        raw_result = await llm.call_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except DailyLimitExceededError:
        raise HTTPException(status_code=429, detail="Daily AI limit reached, try again tomorrow")
    except LLMClientError as e:
        logger.error(f"LLM plan generation error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        logger.error(f"Unexpected error calling LLM for plan: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate AI plan")

    if not isinstance(raw_result, dict):
        raw_result = {}

    # 4. Ground truth normalization & validation
    page_norm = normalize_text_for_numbers(ctx.main_text or "")
    raw_page_text = ctx.main_text or ""
    total_removed_count = 0

    # 4.1 Questions to answer validation (Max 6)
    questions_raw = raw_result.get("questions_to_answer", [])
    valid_questions: list[dict] = []
    if isinstance(questions_raw, list):
        for q in questions_raw:
            if not isinstance(q, dict) or not q.get("question"):
                continue
            draft_ans = strip_urls(str(q.get("draft_answer") or ""))
            draft_ans = remove_financial_advice_phrases(draft_ans)

            # Length validation: max 60 words
            words = draft_ans.split()
            if len(words) > 60:
                draft_ans = " ".join(words[:60])
            
            src = q.get("answer_source", "page")
            if src not in ["page", "needs_info"]:
                src = "page"

            # If marked as page, verify it does not acknowledge missing info
            if src == "page":
                draft_lower = draft_ans.lower()
                for lk in ["en", "es"]:
                    if any(phrase in draft_lower for phrase in MISSING_INFO_ANSWER_PHRASES.get(lk, [])):
                        src = "needs_info"
                        break

            # Numeric validation
            if not all_numbers_in_page(draft_ans, page_norm):
                total_removed_count += 1
                continue
            
            # Origin & Google PAA exact text matching
            origin = "ai"
            q_text = strip_urls(str(q.get("question") or "")).strip()
            if serp_used and serp_data and serp_data.get("people_also_ask"):
                norm_q = normalize_for_paa_match(q_text)
                for paa in serp_data["people_also_ask"]:
                    paa_orig = (paa.get("question") or "").strip()
                    if paa_orig and normalize_for_paa_match(paa_orig) == norm_q:
                        origin = "google_paa"
                        q_text = paa_orig  # Use exact Google text
                        break

            valid_questions.append({
                "question": q_text,
                "draft_answer": draft_ans.strip(),
                "answer_source": src,
                "origin": origin,
            })
            if len(valid_questions) >= 6:
                break

    # 4.2 Suggested H2 structure (Max 7)
    h2_raw = raw_result.get("suggested_h2_structure", [])
    valid_h2: list[dict] = []
    if isinstance(h2_raw, list):
        for h in h2_raw:
            if not isinstance(h, dict) or not h.get("h2"):
                continue
            st = h.get("status", "new")
            if st not in ["existing", "new"]:
                st = "new"
            valid_h2.append({
                "h2": strip_urls(str(h.get("h2") or "")).strip(),
                "purpose": strip_urls(str(h.get("purpose") or "")).strip(),
                "status": st,
            })
            if len(valid_h2) >= 7:
                break

    # 4.3 Suggested table
    table_raw = raw_result.get("suggested_table")
    valid_table: Optional[dict] = None
    if isinstance(table_raw, dict):
        title = strip_urls(str(table_raw.get("title") or "")).strip()
        headers = table_raw.get("headers")
        rows = table_raw.get("rows")
        table_idea = strip_urls(str(table_raw.get("table_idea") or "")).strip() or None

        valid_headers: Optional[list[str]] = None
        valid_rows: Optional[list[list[str]]] = None

        if isinstance(headers, list) and isinstance(rows, list) and len(rows) >= 1:
            clean_headers = [strip_urls(str(h)).strip() for h in headers]
            filtered_rows: list[list[str]] = []
            for r in rows:
                if not isinstance(r, list):
                    continue
                row_str = " ".join([str(c) for c in r])
                if all_numbers_in_page(row_str, page_norm):
                    filtered_rows.append([strip_urls(str(c)).strip() for c in r])
                else:
                    total_removed_count += 1
            
            if len(filtered_rows) >= 2:
                valid_headers = clean_headers
                valid_rows = filtered_rows
            else:
                valid_headers = None
                valid_rows = None
                if not table_idea:
                    table_idea = f"Create a comparison table covering {title or 'key dimensions'} with verified data."

        if title or valid_headers or table_idea:
            valid_table = {
                "title": title or "Comparison Table",
                "headers": valid_headers,
                "rows": valid_rows,
                "table_idea": table_idea,
            }

    # 4.4 Data opportunities (Max 5)
    data_raw = raw_result.get("data_opportunities", [])
    valid_data_opps: list[dict] = []
    if isinstance(data_raw, list):
        for d in data_raw:
            if not isinstance(d, dict) or not d.get("suggestion"):
                continue
            sug = strip_urls(str(d.get("suggestion") or "")).strip()
            stype = strip_urls(str(d.get("source_type") or "")).strip()

            # Discard technical suggestions (schema, structured data, alt text, metadata, etc.)
            check_text = f"{sug} {stype}".lower()
            is_technical = False
            for lk in ["en", "es"]:
                if any(phrase in check_text for phrase in TECHNICAL_DATA_OPP_PHRASES.get(lk, [])):
                    is_technical = True
                    break
            if is_technical:
                continue

            if not all_numbers_in_page(sug, page_norm):
                total_removed_count += 1
                continue
            valid_data_opps.append({
                "suggestion": sug,
                "source_type": stype or "Industry Benchmark / Official Data",
            })
            if len(valid_data_opps) >= 5:
                break

    # 4.5 Paragraphs to add (Max 3, publishable text without verification phrases or financial advice)
    paras_raw = raw_result.get("paragraphs_to_add", [])
    valid_paras: list[dict] = []
    if isinstance(paras_raw, list):
        for p in paras_raw:
            if not isinstance(p, dict) or not p.get("suggested_text"):
                continue
            stext = strip_urls(str(p.get("suggested_text") or "")).strip()
            # Clean editorial verification sentences and financial advice
            stext = remove_verification_phrases(stext)
            stext = remove_financial_advice_phrases(stext)
            if not stext:
                continue

            # Length validation: 40-80 words
            pwords = stext.split()
            if len(pwords) > 80:
                stext = " ".join(pwords[:80])
            
            if not all_numbers_in_page(stext, page_norm):
                total_removed_count += 1
                continue

            valid_paras.append({
                "target_issue": strip_urls(str(p.get("target_issue") or "Content Enhancement")).strip(),
                "suggested_text": stext,
                "placement": strip_urls(str(p.get("placement") or "In body content")).strip(),
            })
            if len(valid_paras) >= 3:
                break

    # 4.6 Inconsistencies (Max 3, values must appear literally in page text)
    incons_raw = raw_result.get("inconsistencies", [])
    valid_incons: list[dict] = []
    if isinstance(incons_raw, list):
        for inc in incons_raw:
            if not isinstance(inc, dict) or not inc.get("issue") or not inc.get("values"):
                continue
            vals = inc.get("values")
            if not isinstance(vals, list) or len(vals) < 2:
                continue
            
            all_vals_found = True
            clean_vals = []
            for v in vals:
                v_str = str(v).strip()
                if not v_str:
                    all_vals_found = False
                    break
                if v_str.lower() not in raw_page_text.lower():
                    all_vals_found = False
                    break
                clean_vals.append(v_str)

            if not all_vals_found:
                continue

            valid_incons.append({
                "issue": strip_urls(str(inc.get("issue") or "")).strip(),
                "values": clean_vals,
                "suggestion": strip_urls(str(inc.get("suggestion") or "")).strip(),
            })
            if len(valid_incons) >= 3:
                break

    # 4.7 Sources to cite (Max 8, built by backend from Google data, why from LLM)
    final_sources_to_cite: list[dict] = []
    if candidate_sources:
        raw_why = raw_result.get("sources_why") or raw_result.get("sources_to_cite_reasons") or raw_result.get("sources_to_cite") or []
        why_by_index: dict[int, str] = {}
        why_by_domain: dict[str, str] = {}
        if isinstance(raw_why, list):
            for item in raw_why:
                if isinstance(item, dict):
                    w = str(item.get("why") or "").strip()
                    w = remove_financial_advice_phrases(w)
                    if "index" in item:
                        try:
                            why_by_index[int(item["index"])] = w
                        except Exception:
                            pass
                    if "domain" in item and isinstance(item["domain"], str):
                        why_by_domain[item["domain"].lower().strip().replace("www.", "")] = w
        
        for idx, cand in enumerate(candidate_sources, start=1):
            why_str = why_by_index.get(idx) or why_by_domain.get(cand["domain"]) or ""
            if not why_str:
                if lang.startswith("es"):
                    why_str = "Fuente de referencia relevante para contrastar información sobre este tema."
                else:
                    why_str = "Authoritative reference for relevant industry benchmarks and context."
            final_sources_to_cite.append({
                "url": cand["url"],
                "title": cand["title"],
                "domain": cand["domain"],
                "found_in": cand["found_in"],
                "why": why_str,
            })

    # 5. Build combined schema
    article_schema, article_warnings = build_article_schema(ctx, expected_type, {})
    combined_schema = build_combined_schema(ctx, article_schema, valid_questions)

    # 6. Warnings
    all_warnings = warnings + list(article_warnings)
    if total_removed_count > 0:
        all_warnings.append(
            f"{total_removed_count} suggestions were removed because they contained figures not found on the page."
        )

    response_data = {
        "questions_to_answer": valid_questions,
        "suggested_h2_structure": valid_h2,
        "suggested_table": valid_table,
        "data_opportunities": valid_data_opps,
        "paragraphs_to_add": valid_paras,
        "inconsistencies": valid_incons,
        "sources_to_cite": final_sources_to_cite,
        "combined_schema": combined_schema,
        "warnings": all_warnings,
        "serp_query": serp_query if (serp_used or serp_query) else None,
        "serp_market": serp_market,
        "serp_used": serp_used,
        "serp_paa_found": serp_paa_found,
    }

    # 7. Store in cache
    put_ai_plan_cache(cache_key, response_data, now_ts + 86400)

    return AIPlanResponse(**response_data)



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
