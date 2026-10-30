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
import httpx

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
    BriefExportRequest,
    AhrefsOffpageRequest,
    AhrefsOffpageResponse,
    AIRewriteRequest,
    AIRewriteResponse,
    AIRewriteScoreRequest,
    AIRewriteScoreResponse,
    DimensionScoreComparison,
    RewriteBriefExportRequest,
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
    is_excluded_source,
    normalize_domain,
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
    DISCARD_QUESTION_KEYWORDS,
    SENSITIVE_LEGAL_KEYWORDS,
    EN_ES_STOP_WORDS,
    generate_ahrefs_recommendations,
    strip_page_meta_references,
)
from src.utils.docx_brief import (
    generate_editor_brief_docx,
    generate_rewrite_draft_docx,
    sanitize_domain_for_filename,
)
from src.detectors.query_match import get_missing_lead_query_terms
from src.services.ahrefs_client import (
    AhrefsClient,
    AhrefsAuthError,
    get_cached_ahrefs_data,
    put_cached_ahrefs_data,
    get_ahrefs_daily_count,
    increment_ahrefs_daily_count,
    reset_ahrefs_cache,
    reset_ahrefs_daily_usage,
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


class DynamicCORSMiddleware(CORSMiddleware):
    def is_allowed_origin(self, origin: str) -> bool:
        if super().is_allowed_origin(origin):
            return True
        current_regex = settings.cors_origin_regex if settings else ""
        if current_regex:
            try:
                return bool(re.fullmatch(current_regex, origin))
            except Exception:
                return False
        return False


# CORSMiddleware must be the outermost middleware so CORS headers
# (e.g. access-control-allow-origin) are added to all responses,
# including 401 and 429 errors from access_code_middleware.
app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/check")
async def check_access_code():
    """Verify access code validity."""
    return {"status": "ok"}


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health_check(request: Request):
    """Health check endpoint. Supports GET and HEAD."""
    if request.method == "HEAD":
        return Response(status_code=200)
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
        json_ld["mainEntityOfPage"] = ctx.url
    elif "mainEntityOfPage" not in json_ld or not json_ld["mainEntityOfPage"]:
        json_ld["mainEntityOfPage"] = "REPLACE_WITH_PAGE_URL"

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


def normalize_heading(text: str) -> str:
    """Normalize heading text by stripping accents/diacritics, punctuation, extra whitespace, and lowercasing."""
    if not text:
        return ""
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    clean = re.sub(r"[^\w\s]", "", without_accents).lower()
    return re.sub(r"\s+", " ", clean).strip()


def get_heading_words(text: str) -> set[str]:
    """Extract individual words from normalized heading text, filtering out stop words."""
    norm = normalize_heading(text)
    return {w for w in norm.split() if w and w not in EN_ES_STOP_WORDS}


def headings_share_words(s1: str, s2: str, threshold: float = 0.6) -> bool:
    """Check if two headings share >= threshold of their words (in either direction)."""
    w1 = set(s1.split())
    w2 = set(s2.split())
    if not w1 or not w2:
        return False
    shared = len(w1 & w2)
    return (shared / len(w1) >= threshold) or (shared / len(w2) >= threshold)


def extract_draft_opening_paragraph(draft_markdown: str) -> str:
    """
    Extract the first substantive body paragraph from markdown draft.
    Skips headings (#), markdown tables (|), images (![), and standalone CTA buttons/links.
    """
    if not draft_markdown:
        return ""
    paras = [p.strip() for p in re.split(r'\n\s*\n', draft_markdown) if p.strip()]
    for p in paras:
        if p.startswith("#") or p.startswith("|") or p.startswith("!["):
            continue
        p_no_gaps = re.sub(r'\[EDITOR:[^\]]*\]', '', p).strip()
        # Exclude standalone button/link lines
        if re.match(r'^(?:[\*\-\+]\s+|\d+\.\s+)?\[[^\]]+\]\([^)]+\)\s*$', p_no_gaps):
            continue
        # Also clean markdown link wrappers to get plain text
        clean_p = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', p)
        clean_p = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', clean_p)
        return clean_p.strip()
    return ""



def extract_question_from_text(text: str) -> Optional[str]:
    """
    If the text has '?' (or starts with '¿') within the first 25 words,
    the question is the text up to and including that '?'.
    """
    if not text:
        return None
    t = text.strip()
    q_pos = t.find("?")
    if q_pos != -1:
        prefix = t[:q_pos + 1].strip()
        words = prefix.split()
        if 2 <= len(words) <= 25:
            if "¿" in prefix:
                inv_pos = prefix.find("¿")
                return prefix[inv_pos:].strip()
            return prefix
    if t.startswith("¿"):
        words = t.split()
        if 2 <= len(words) <= 25:
            return t
    return None


def extract_original_faq(main_html: str, main_text: str) -> tuple[Optional[str], list[str]]:
    """
    Detects if the original article has an FAQ H2 and extracts the exact H2 title and questions.
    Returns (faq_h2_title, list_of_question_strings).
    """
    faq_re = re.compile(r'\b(?:faq|faqs|frequently\s+asked\s+questions|preguntas\s+frecuentes)\b', re.I)
    faq_h2: Optional[str] = None
    questions: list[str] = []

    def _process_element(el) -> Optional[str]:
        if not el:
            return None
        t = el.get_text(" ", strip=True)
        q = extract_question_from_text(t)
        if q:
            return q
        if el.name in ("h3", "h4", "summary", "dt"):
            words = t.split()
            if 2 <= len(words) <= 20:
                return t
        return None

    if main_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(main_html, "lxml")
        target_h2 = None
        for h2 in soup.find_all(["h2", "h3"]):
            text = h2.get_text(" ", strip=True)
            if faq_re.search(text):
                faq_h2 = text
                target_h2 = h2
                break

        if target_h2:
            curr = target_h2.next_sibling
            while curr:
                if getattr(curr, "name", None) in ("h1", "h2"):
                    break
                tag_name = getattr(curr, "name", None)
                if tag_name in ("h3", "h4", "summary", "dt", "li", "p"):
                    q = _process_element(curr)
                    if q and q not in questions:
                        questions.append(q)
                elif hasattr(curr, "find_all"):
                    for sub in curr.find_all(["h3", "h4", "summary", "dt", "li", "p"]):
                        q = _process_element(sub)
                        if q and q not in questions:
                            questions.append(q)
                curr = curr.next_sibling

            if not questions and target_h2.parent:
                after = False
                for sub in target_h2.parent.find_all(["h2", "h3", "h4", "summary", "dt", "li", "p"]):
                    if sub == target_h2:
                        after = True
                        continue
                    if not after:
                        continue
                    if sub.name in ("h1", "h2"):
                        break
                    q = _process_element(sub)
                    if q and q not in questions:
                        questions.append(q)

    if main_text:
        lines = main_text.split("\n")
        in_faq = False
        for line in lines:
            line_str = line.strip()
            if re.match(r'^##\s+', line_str):
                h_text = re.sub(r'^##\s+', '', line_str).strip()
                if faq_re.search(h_text):
                    in_faq = True
                    if not faq_h2:
                        faq_h2 = h_text
                    continue
                else:
                    if in_faq:
                        break
            elif in_faq:
                if not line_str:
                    continue
                clean_line = re.sub(r'^(?:###\s+|##\s+|[\*\-\+]\s+|\d+\.\s+)', '', line_str).strip()
                q = extract_question_from_text(clean_line)
                if q and q not in questions:
                    questions.append(q)
                elif re.match(r'^\*\*(.*?\?)\*\*', clean_line):
                    qm2 = re.match(r'^\*\*(.*?\?)\*\*', clean_line)
                    q = qm2.group(1).strip()
                    if q and q not in questions:
                        questions.append(q)
                elif clean_line.startswith("### "):
                    h3_text = clean_line[4:].strip()
                    if h3_text and 2 <= len(h3_text.split()) <= 20 and h3_text not in questions:
                        questions.append(h3_text)

    cleaned: list[str] = []
    seen = set()
    for q in questions:
        q_clean = q.strip(" *#_-:\t\r\n")
        if q_clean and q_clean.lower() not in seen:
            seen.add(q_clean.lower())
            cleaned.append(q_clean)

    return faq_h2, cleaned


def all_numbers_in_page(text: str, page_norm: str) -> bool:
    """Returns True if every number in text is found in page_norm. Ignores numbers inside [EDITOR: ...] placeholders."""
    # Strip [EDITOR: ...] placeholders so editor gap instructions don't trigger numeric validation failures
    text_to_check = re.sub(r'\[EDITOR:[^\]]*\]', '', text)
    tokens = extract_numbers_with_context(text_to_check)
    for tok in tokens:
        escaped = re.escape(tok)
        if not re.search(r'(?<!\d)' + escaped + r'(?!\d)', page_norm):
            return False
    return True


def strip_urls(text: str) -> str:
    """Removes all URLs from text while preserving [EDITOR: ...] placeholders intact."""
    if not text:
        return ""
    placeholders: list[str] = []
    def repl(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"___EDITOR_GAP_{len(placeholders)-1}___"
    
    t_sub = re.sub(r'\[EDITOR:[^\]]*\]', repl, text)
    t = re.sub(r'https?://[^\s]+', '', t_sub)
    for i, p in enumerate(placeholders):
        t = t.replace(f"___EDITOR_GAP_{i}___", p)
    return re.sub(r'\s+', ' ', t).strip()


def normalize_link_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase scheme/host, drop 'www.', fragment and trailing slash."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return (url or "").strip()
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    query = f"?{p.query}" if p.query else ""
    return f"{(p.scheme or '').lower()}://{host}{path}{query}"


def extract_original_links(main_html: str, base_url: Optional[str] = None) -> list[dict]:
    """
    Extract unique links (anchor text + absolute href) from the main content HTML.
    Relative hrefs are resolved against base_url; mailto/tel/javascript/anchor-only links are skipped.
    Returns [] when main_html is empty (e.g. pasted text).
    """
    if not main_html:
        return []
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(main_html, "lxml")
    links: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or re.match(r'^(mailto|tel|javascript|data):', href, re.I):
            continue
        absolute = urljoin(base_url, href) if base_url else href
        if not re.match(r'^https?://', absolute, re.I):
            continue
        key = normalize_link_url(absolute)
        if key in seen:
            continue
        seen.add(key)
        text = re.sub(r'\s+', ' ', a.get_text(" ", strip=True)).strip() or absolute
        links.append({"text": text, "url": absolute})
    return links


def extract_original_images(main_html: str, base_url: Optional[str] = None) -> list[dict]:
    """
    Extract unique images (src absolute + alt) from the main content HTML.
    Ignores icons, tracking pixels (1x1 or keywords), and data: URIs.
    Returns [] when main_html is empty.
    """
    if not main_html:
        return []
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(main_html, "lxml")
    images: list[dict] = []
    seen: set[str] = set()

    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "").strip()
        if not src or src.startswith("data:"):
            continue

        absolute = urljoin(base_url, src) if base_url else src
        if not re.match(r'^https?://', absolute, re.I):
            continue

        # Check for tracking pixel / icon
        width = str(img.get("width") or "").strip()
        height = str(img.get("height") or "").strip()
        if (width == "1" and height == "1") or (width == "0" or height == "0"):
            continue

        src_lower = absolute.lower()
        if any(kw in src_lower for kw in ["pixel", "tracking", "/favicon", "icon-16", "icon-32", "1x1"]):
            continue

        key = normalize_link_url(absolute)
        if key in seen:
            continue
        seen.add(key)

        alt = (img.get("alt") or "").strip()
        images.append({"alt": alt, "src": absolute})

    return images


_MD_IMG_RE = re.compile(r'!\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+"[^"]*")?\)')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+"[^"]*")?\)')


def filter_draft_urls(line: str, allowed: set[str]) -> str:
    """
    Remove URLs that are not in `allowed` (normalized).
    Markdown images ![alt](src) and Markdown links [text](url) to allowed URLs are kept intact.
    Markdown images to unknown URLs are removed or reduced to alt text;
    Markdown links to unknown URLs are reduced to their anchor text; unknown bare URLs are deleted.
    """
    kept: list[str] = []

    # 1. Protect allowed Markdown images
    def _img(m: re.Match) -> str:
        if normalize_link_url(m.group(2)) in allowed:
            kept.append(m.group(0))
            return f"___KEPT_LINK_{len(kept)-1}___"
        # If image not in allowed list, drop it (or keep alt if present)
        alt = m.group(1).strip()
        return f"[Image: {alt}]" if alt else ""

    out = _MD_IMG_RE.sub(_img, line)

    # 2. Protect allowed Markdown links
    def _md(m: re.Match) -> str:
        if normalize_link_url(m.group(2)) in allowed:
            kept.append(m.group(0))
            return f"___KEPT_LINK_{len(kept)-1}___"
        return m.group(1)

    out = _MD_LINK_RE.sub(_md, out)

    # 3. Strip unknown bare URLs
    def _bare(m: re.Match) -> str:
        raw = m.group(0)
        trail = ""
        while raw and raw[-1] in ".,;:!?)":
            trail = raw[-1] + trail
            raw = raw[:-1]
        if normalize_link_url(raw) in allowed:
            return m.group(0)
        return trail

    out = re.sub(r'https?://[^\s]+', _bare, out)
    for i, k in enumerate(kept):
        out = out.replace(f"___KEPT_LINK_{i}___", k)
    return out


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
    s = settings if (settings is not None and (settings.ai_enabled or settings.serp_enabled or settings.access_required or settings.ahrefs_enabled)) else get_settings()
    return {
        "version": s.app_version,
        "ai_enabled": s.ai_enabled,
        "serp_enabled": s.serp_enabled,
        "access_required": s.access_required,
        "ahrefs_enabled": s.ahrefs_enabled,
    }


@app.get("/api/scoring-weights")
async def get_scoring_weights():
    """Get current scoring configuration."""
    return settings.scoring_weights


@app.post("/api/audit", response_model=AuditResponse, response_model_exclude_none=True)
async def audit_url(request: AuditRequest):
    """
    Analyze a URL, raw text, or HTML content fragment for LLM citability.
    """
    global scraper
    if not request.url and not request.content_text and not request.content_html:
        raise HTTPException(status_code=400, detail="Must provide either URL, content_text, or content_html")

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
- Logical connectors (Therefore, However, Because, etc.) must ONLY be used when that logical relationship genuinely exists between ideas; never insert them artificially to boost a metric.
- CRITICAL COPYWRITING RULE: The suggested lead paragraph must be written strictly as final, publishable web copy. NEVER refer to 'the page', 'this page', 'the article', 'la página', 'esta página', 'the announcement\'s disclaimer', or similar meta-commentary.
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

    lead_has_unverified_numbers = False
    if suggested_lead:
        if not all_numbers_in_page(suggested_lead, page_norm):
            lead_has_unverified_numbers = True
        suggested_lead = remove_financial_advice_phrases(suggested_lead)
        suggested_lead = strip_page_meta_references(suggested_lead)

    if lead_has_unverified_numbers or (suggested_lead and not all_numbers_in_page(suggested_lead, page_norm)):
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

    # 1. Check in-memory 24h cache (includes request.query to differentiate regenerated plans)
    cache_key_raw = f"plan::{ctx.url or ''}::{ctx.main_text or ''}::{request.target_query or ctx.target_query or ''}::{request.query or ''}::{current_settings.serp_enabled}"
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
    serp_failed = False
    candidate_sources: list[dict] = []
    warnings: list[str] = []

    if current_settings.serp_enabled:
        try:
            if request.query and request.query.strip():
                serp_query = request.query.strip()
            else:
                serp_query = await resolve_serp_query(ctx, llm, request.target_query)
            _, _, default_market = get_market_for_language(ctx.language or "en")
            serp_market = default_market
            serp_client = SerpClient(current_settings)
            serp_data = await serp_client.fetch_serp_live(
                query=serp_query,
                language=ctx.language or "en",
                audited_url=ctx.url or "",
            )
            serp_used = True
            serp_market = serp_data.get("market") or default_market

            # Build candidate sources (max 8, AI Overview first, then Organic top 10, no duplicate domains)
            seen_domains = set()
            audited_domain = ctx.url or ""
            for src in serp_data.get("ai_overview_sources", []):
                u = src.get("url") or ""
                t = src.get("title") or ""
                dom = (src.get("domain") or "").lower().strip()
                if not dom and u:
                    dom = normalize_domain(u)
                if dom and not is_excluded_source(dom, url=u, title=t, page_domain=audited_domain):
                    if dom not in seen_domains:
                        seen_domains.add(dom)
                        candidate_sources.append({
                            "url": u,
                            "title": t or dom,
                            "domain": dom,
                            "found_in": "AI Overview",
                        })
                if len(candidate_sources) >= 8:
                    break

            if len(candidate_sources) < 8:
                for src in serp_data.get("organic", []):
                    u = src.get("url") or ""
                    t = src.get("title") or ""
                    dom = (src.get("domain") or "").lower().strip()
                    if not dom and u:
                        dom = normalize_domain(u)
                    if dom and not is_excluded_source(dom, url=u, title=t, page_domain=audited_domain):
                        if dom not in seen_domains:
                            seen_domains.add(dom)
                            candidate_sources.append({
                                "url": u,
                                "title": t or dom,
                                "domain": dom,
                                "found_in": "Organic top 10",
                            })
                    if len(candidate_sources) >= 8:
                        break
        except SerpDailyLimitExceededError as e:
            logger.warning(f"DataForSEO daily limit reached: {e}")
            serp_failed = True
            serp_used = False
            serp_data = None
            _, _, serp_market = get_market_for_language(ctx.language or "en")
            warnings.append("Daily Google data limit reached; questions and sources are AI-suggested only.")
        except SerpClientError as e:
            logger.warning(f"DataForSEO error: {e}")
            serp_failed = True
            serp_used = False
            serp_data = None
            _, _, serp_market = get_market_for_language(ctx.language or "en")
            warnings.append("Google data unavailable for this plan; questions and sources are AI-suggested only.")
        except Exception as e:
            logger.warning(f"Unexpected DataForSEO error: {e}")
            serp_failed = True
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
    target_q = (request.target_query or ctx.target_query or "").strip()

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
        "6. In 'data_opportunities', suggest factual data, statistics, and domain benchmarks only. DO NOT suggest technical SEO fixes (no schema, no structured data, no alt text, no metadata, no speed, no internal links).\n"
        "7. Questions must be strictly relevant to the specific topic of the page. Forbidden to ask questions about stock prices, share prices, revenue, financial returns, or investment recommendations (e.g. 'stock price', 'cotización', 'revenue', 'rentabilidad', 'should I invest').\n"
        "8. In 'paragraphs_to_add' and all suggested text, logical connectors (Therefore, However, Because, etc.) must ONLY be used when that logical relationship genuinely exists between ideas; never insert them artificially to boost a metric.\n"
        "9. CRITICAL COPYWRITING RULE: The suggested lead paragraph ('suggested_lead'), all 'paragraphs_to_add' (new paragraphs), and any 'draft_answer' with answer_source 'page', must be written strictly as final, publishable web copy ready for publication. NEVER refer to 'the page', 'this page', 'the page\'s', 'la página', 'esta página', 'the announcement\'s disclaimer', or any meta-commentary about the page or document itself.\n"
        "10. FACTUAL ACCURACY & NO UNBACKED FLUFF: Do NOT add superlatives or rankings ('one of the most', 'the best', 'the largest', 'the most iconic') not literally backed by the page text snippet. Do NOT deduce or infer unstated facts from translations of foreign proper names (e.g. do NOT assert that a stand is covered simply by translating 'Tribuna Copertura').\n"
        "11. PROMISE INTEGRITY IN HEADINGS: Each suggested H2 in 'suggested_h2_structure' must strictly promise ONLY content that the section actually contains. Never create H2s that promise features or elements absent from the text (e.g. do NOT promise 'Layout and Roof' if there is no content about the roof).\n"
        "12. TARGET QUERY IN OPENING LEAD: When a Target Query is provided, the suggested opening lead paragraph ('suggested_lead') MUST naturally and literally contain all of its significant search words (do not substitute with synonyms or foreign language variants; e.g. 'ground' or 'Stadio' do not satisfy 'stadium')."
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
            parts.append(f"Candidate Sources Found on Google for '{serp_query}':\n{src_lines}\n* INSTRUCTION: For each candidate source (1 to {len(candidate_sources)}), evaluate if it is suitable to cite in the text. Return in 'sources_why' a concise 1-sentence 'why' in {lang_instruction} explaining why or how this audited page should cite or link to it. If the source is NOT suitable for citation (such as business/company directories, pages of an unrelated entity or topic, or irrelevant content), return \"why\": null. Do NOT return any URLs.")
        if parts:
            google_context_text = "\n\nReal Google Search Data (from DataForSEO):\n" + "\n\n".join(parts) + "\n"

    sources_why_schema = ""
    if candidate_sources:
        sources_why_schema = """,
  "sources_why": [
    {{
      "index": 1,
      "why": "Concise 1-sentence explanation why this page should cite this source, or null if unsuitable to cite"
    }}
  ]"""

    target_query_info = f"\nTarget Query: {target_q}" if target_q else ""
    user_prompt = f"""Generate an improvement plan for the following web page to optimize its citability in AI engines (ChatGPT, Perplexity, Gemini).

Page Information:
URL: {ctx.url or 'N/A'}
Title: {ctx.title or 'N/A'}
H1: {ctx.h1 or 'N/A'}{target_query_info}
Language: {lang}
Content Type: {ctx.content_type}
Detected Author: {ctx.detected_author or 'Not detected'}
Detected Publisher: {ctx.detected_publisher or 'Not detected'}
Detected Date Published: {ctx.detected_date_published or 'Not detected'}
Detected Date Modified: {ctx.detected_date_modified or 'Not detected'}

Original First Paragraph:
\"\"\"{ctx.first_paragraph or 'None'}\"\"\"

Failing Submetrics:
{failing_info or 'None'}

Main Text Snippet (First 8000 chars):
\"\"\"{ctx.main_text}\"\"\"{google_context_text}

Generate a JSON object with EXACTLY this structure:
{{
  "suggested_lead": {{
    "original": "{ctx.first_paragraph or ''}",
    "suggested": "40-60 words optimized direct-answer paragraph in {lang_instruction}",
    "rationale": "Clear explanation of changes made in {lang_instruction} (maximum 2 sentences)"
  }},
  "json_ld": {{
    "description": "Short 1-2 sentence summary of the page in {lang_instruction}",
    "about": [
      {{
        "@type": "Thing",
        "name": "Main entity or topic"
      }}
    ],
    "mentions": [
      {{
        "@type": "Thing",
        "name": "Secondary entity or concept"
      }}
    ]
  }},
  "questions_to_answer": [
    {{
      "question": "Question text in {lang_instruction}",
      "draft_answer": "Direct, publishable answer (40-70 words). If answer_source is 'page', must only use facts from page text. If answer_source is 'needs_info', write ready-to-publish copy using facts on the page and represent any missing information as a visible gap in this exact format: [EDITOR: missing information description in {lang_instruction} — source type]. A gap can ONLY request data NOT present in the page text.",
      "answer_source": "page" // 'page' ONLY if the page directly answers the question. If the page lacks the necessary data to answer it completely, set to 'needs_info'. NEVER write a meta-explanation stating what the page lacks; write the copy with [EDITOR: ...] gaps.
    }}
  ],
  "suggested_h2_structure": [
    {{
      "h2": "Suggested or preserved H2 heading text in {lang_instruction}",
      "purpose": "Brief explanation of user intent / AEO goal in exactly 1 sentence",
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
- suggested_lead: An optimized opening paragraph (40-60 words) that immediately answers the primary user intent, states the main entity in the first sentence, uses strictly facts from the provided text, and removes fluff. Provide 'rationale' in maximum 2 sentences. When a Target Query is provided, the opening paragraph MUST naturally and literally contain all its significant search terms without replacing them with synonyms or translations in another language.
- json_ld: Factual description (1-2 sentences), about (maximum 3 main entities/topics), and mentions (maximum 5 secondary entities/concepts). Factual only; do NOT invent figures.
- questions_to_answer: 3 to 6 questions. Formulate direct, user-focused questions. Prioritize real Google 'People Also Ask' questions if provided. Draft answers must be 40-70 words. Set answer_source to 'page' ONLY if the page actually answers the question directly. When the page does not contain the answer, set answer_source to 'needs_info' and write a ready-to-publish answer where the FIRST sentence must answer the question directly with the missing information explicitly marked as a gap using this exact format: [EDITOR: what data is missing — source type] placed precisely where the missing data belongs (e.g. "Palermo FC's current ownership is [EDITOR: owner and stake — official club statements]."). When data is missing, the answer must NOT affirm or speculate on ANYTHING outside the editor gap: no yes/no answers, and no claims about whether something exists or does not exist (e.g. do NOT say 'Club X is not owned by Y' or 'Tours operate [EDITOR]'). The gap must be right in the opening / first sentence. Correct examples: "Palermo FC's current ownership is [EDITOR: owner and stake — official club statements]." and "[EDITOR: whether stadium tours are available, with days and prices — official club ticketing].". Do NOT fill with unrelated page data (like stadium capacity). The description inside [EDITOR: ...] MUST be written strictly in {lang_instruction} (the page's language, never in another language by default). An editor gap can ONLY request data that is NOT present in the page text; if a fact, figure, or detail is already in the text, you MUST include it directly rather than making a placeholder. Example: "The largest stadium in France is [EDITOR: stadium name and capacity — official stadium records]. The CEPAC Vélodrome, with 67,000 seats, is one of the country's most iconic football grounds." You may use facts that ARE on the page, but NEVER invent missing figures (any number not in the text will cause the answer to be discarded), and NEVER write meta-commentary like "This guide does not confirm...".
- suggested_h2_structure: Logical H2 structure covering main aspects. Max 7 items. Provide 'purpose' in exactly 1 sentence. Each suggested H2 must strictly promise only content that the section actually contains. Never create H2s that promise features or elements absent from the text (e.g. do NOT promise 'Layout and Roof' if there is no content about the roof).
- sources_why: For each candidate source, provide 'why' in exactly 1 sentence. If the source is NOT suitable to cite in the text (business directories, pages of a different entity, unrelated content), set 'why': null.
- suggested_table: If the content has comparative/structured elements, provide 2-4 rows. If the page lacks enough comparative data to build 2 rows reliably without inventing numbers, provide null for headers/rows and give 'table_idea'.
- data_opportunities: 2 to 5 suggestions of data points or factual metrics to strengthen the content. Factual and content data only. PROHIBITED: Do NOT suggest technical SEO fixes (no schema, no structured data, no alt text, no metadata, no speed, no internal links).
- paragraphs_to_add: 1 to 3 paragraphs ready to publish without editor notes or verification comments.
- inconsistencies: 0 to 3 internal contradictions found on the page (different figures, dates, or names for the same thing). The conflicting values MUST appear literally in the page text snippet. If none are found, return an empty array [].
- In financial, investment, or regulated topics, do NOT give investment advice, recommendations, or calls to action to investors; strictly describe what the page says.
- Questions must be strictly relevant to the specific topic of the page. Forbidden to ask questions about stock prices, share prices, revenue, financial returns, or investment recommendations.
- Logical connectors (Therefore, However, Because, etc.) in paragraphs and text must ONLY be used when genuine logical relationships exist between ideas; never artificially insert them to boost a score.
- CRITICAL COPYWRITING RULE: The suggested lead paragraph ('suggested_lead'), all suggested paragraphs ('paragraphs_to_add') and all answers ('draft_answer') must be written strictly as final, publishable web copy. NEVER refer to 'the page', 'this page', 'the page\'s', 'la página', 'esta página', 'this guide', 'this article', 'the announcement\'s disclaimer', or similar meta-commentary.
- FACTUAL ACCURACY & NO UNBACKED FLUFF: Do NOT add superlatives or rankings ("one of the most", "the best", "the largest", "the most iconic") that are not literally backed by the page text snippet. Do NOT deduce or infer unstated facts from translations of foreign proper names (e.g. do NOT assert that a stand is covered simply by translating "Tribuna Copertura").
- Language: Strictly {lang_instruction}. All text, including the descriptions inside [EDITOR: ...], must be strictly in {lang_instruction}.
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

            # Length validation: max 70 words
            words = draft_ans.split()
            if len(words) > 70:
                draft_ans = " ".join(words[:70])
            
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

            # Strip meta-references ("the page", "this page", "this guide", "this article", etc.)
            draft_ans = strip_page_meta_references(draft_ans)
            if not draft_ans.strip():
                continue

            # For needs_info (and page), verify that there is publishable copy left (not just [EDITOR: ...] placeholders)
            text_without_editor_gaps = re.sub(r'\[EDITOR:[^\]]*\]', '', draft_ans).strip()
            # If after stripping gaps there is no substantive text left, discard the question
            if not re.search(r'[a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]', text_without_editor_gaps):
                continue

            # Discard questions about stock prices, share prices, revenue, returns, or investing
            q_raw_text = str(q.get("question") or "")
            q_lower = q_raw_text.lower()
            is_forbidden_q = False
            for lk in ["en", "es"]:
                if any(kw in q_lower for kw in DISCARD_QUESTION_KEYWORDS.get(lk, [])):
                    is_forbidden_q = True
                    break
            if is_forbidden_q:
                continue

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
    # Collect real H2 headings from page (from ctx.existing_h2s or extracted from main_text)
    page_h2_candidates: list[str] = list(getattr(ctx, "existing_h2s", []) or [])
    if not page_h2_candidates and ctx.main_text:
        # Fallback to headings extracted if available
        pass
    norm_candidates = [(orig_h, normalize_heading(orig_h)) for orig_h in page_h2_candidates if normalize_heading(orig_h)]

    # Compute entity words appearing in >= 50% of real page H2s (with count >= 2 when multiple H2s exist)
    total_real_h2s = len(norm_candidates)
    word_freq_counts: dict[str, int] = {}
    for _, norm_h in norm_candidates:
        for w in get_heading_words(norm_h):
            word_freq_counts[w] = word_freq_counts.get(w, 0) + 1

    entity_words: set[str] = {
        w for w, cnt in word_freq_counts.items()
        if (cnt >= 2 if total_real_h2s >= 2 else cnt >= 1) and (cnt / total_real_h2s >= 0.5)
    }

    h2_raw = raw_result.get("suggested_h2_structure", [])
    valid_h2: list[dict] = []
    if isinstance(h2_raw, list):
        for h in h2_raw:
            if not isinstance(h, dict) or not h.get("h2"):
                continue
            clean_h2 = strip_urls(str(h.get("h2") or "")).strip()
            norm_sug = normalize_heading(clean_h2)
            
            # Deterministic check:
            # 1. Exact match -> 'present'
            st = "new"
            matched_original_h2: Optional[str] = None
            exact_match = next((orig_h for orig_h, norm_h in norm_candidates if norm_sug == norm_h), None)

            if exact_match is not None:
                st = "present"
                matched_original_h2 = exact_match
            else:
                # 2. Overlapping match: remove entity words & stop words
                # Rename if:
                # (a) share >= 2 words and overlap >= 60%, OR
                # (b) ALL remaining words of real H2 (at least 1) are contained in suggested H2
                sug_words = get_heading_words(norm_sug) - entity_words
                candidates_rename: list[tuple[float, int, str]] = []
                if sug_words:
                    for orig_h, norm_h in norm_candidates:
                        real_words = get_heading_words(norm_h) - entity_words
                        if not real_words:
                            continue
                        shared = sug_words & real_words
                        ratio1 = len(shared) / len(sug_words) if sug_words else 0
                        ratio2 = len(shared) / len(real_words) if real_words else 0
                        overlap = max(ratio1, ratio2)

                        cond_a = len(shared) >= 2 and overlap >= 0.6
                        cond_b = len(real_words) >= 1 and real_words.issubset(sug_words)

                        if cond_a or cond_b:
                            candidates_rename.append((overlap, len(shared), orig_h))

                if candidates_rename:
                    # Pick highest overlap, breaking ties by number of shared words
                    candidates_rename.sort(key=lambda x: (x[0], x[1]), reverse=True)
                    st = "rename"
                    matched_original_h2 = candidates_rename[0][2]
                elif norm_sug and page_norm and (norm_sug in page_norm):
                    st = "existing"
                else:
                    st = h.get("status", "new")
                    if st not in ["existing", "new", "present", "rename"]:
                        st = "new"

            valid_h2.append({
                "h2": clean_h2,
                "purpose": strip_urls(str(h.get("purpose") or "")).strip(),
                "status": st,
                "original_h2": matched_original_h2,
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
            stext = strip_page_meta_references(stext)
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
        why_by_index: dict[int, Optional[str]] = {}
        why_by_domain: dict[str, Optional[str]] = {}
        if isinstance(raw_why, list):
            for item in raw_why:
                if isinstance(item, dict):
                    w_val = item.get("why")
                    if w_val is None:
                        w = None
                    else:
                        w = str(w_val).strip()
                        w = remove_financial_advice_phrases(w)
                    if "index" in item:
                        try:
                            why_by_index[int(item["index"])] = w
                        except Exception:
                            pass
                    if "domain" in item and isinstance(item["domain"], str):
                        why_by_domain[item["domain"].lower().strip().replace("www.", "")] = w
        
        for idx, cand in enumerate(candidate_sources, start=1):
            why_candidate = why_by_index.get(idx)
            if why_candidate is None and cand["domain"] in why_by_domain:
                why_candidate = why_by_domain.get(cand["domain"])
            
            # Discard sources where why is null, None, or empty
            if not why_candidate:
                continue
            why_str = str(why_candidate).strip()
            if not why_str or why_str.lower() in ["null", "none"]:
                continue

            final_sources_to_cite.append({
                "url": cand["url"],
                "title": cand["title"],
                "domain": cand["domain"],
                "found_in": cand["found_in"],
                "why": why_str,
            })

    # 4.8 Lead paragraph validation & numeric check
    lead_data = raw_result.get("suggested_lead") or raw_result.get("lead_paragraph") or {}
    original_lead = (ctx.first_paragraph or "").strip()
    suggested_lead_text = lead_data.get("suggested", "").strip() if isinstance(lead_data, dict) else ""
    rationale_lead = lead_data.get("rationale", "").strip() if isinstance(lead_data, dict) else ""

    lead_has_unverified_numbers = False
    if suggested_lead_text:
        if not all_numbers_in_page(suggested_lead_text, page_norm):
            lead_has_unverified_numbers = True
        suggested_lead_text = remove_financial_advice_phrases(suggested_lead_text)
        suggested_lead_text = strip_page_meta_references(suggested_lead_text)

    if lead_has_unverified_numbers or (suggested_lead_text and not all_numbers_in_page(suggested_lead_text, page_norm)):
        suggested_lead_text = original_lead
        rationale_lead = "The original lead paragraph was kept because the suggested lead contained unverified figures."
        warnings.append("The suggested lead contained figures not found on the page and was discarded.")

    if not suggested_lead_text:
        suggested_lead_text = original_lead or "No lead paragraph available."
    if not rationale_lead:
        rationale_lead = "Optimized for directness, inverted pyramid structure, and entity clarity."

    lead_paragraph_fix = LeadParagraphFix(
        original=original_lead,
        suggested=suggested_lead_text,
        rationale=rationale_lead,
    )

    # 5. Build combined schema
    json_ld_raw = raw_result.get("json_ld") or raw_result.get("schema_article") or {}
    if not isinstance(json_ld_raw, dict):
        json_ld_raw = {}

    article_schema, article_warnings = build_article_schema(ctx, expected_type, json_ld_raw)

    # Validate numeric figures in LLM-generated JSON-LD text fields
    removed_schema_count = 0
    for field in ["description", "alternativeHeadline"]:
        if field in article_schema and isinstance(article_schema[field], str) and article_schema[field]:
            if not all_numbers_in_page(article_schema[field], page_norm):
                del article_schema[field]
                removed_schema_count += 1

    for field in ["about", "mentions"]:
        if field in article_schema:
            val = article_schema[field]
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
                            removed_schema_count += 1
                    elif isinstance(item, str):
                        if all_numbers_in_page(item, page_norm):
                            valid_items.append(item)
                        else:
                            removed_schema_count += 1
                max_items = 3 if field == "about" else 5
                article_schema[field] = valid_items[:max_items]
            elif isinstance(val, dict):
                item_ok = True
                for k in ["name", "description"]:
                    if k in val and isinstance(val[k], str) and val[k]:
                        if not all_numbers_in_page(val[k], page_norm):
                            item_ok = False
                            break
                if not item_ok:
                    del article_schema[field]
                    removed_schema_count += 1

    if removed_schema_count > 0:
        warnings.append(
            f"{removed_schema_count} Schema.org elements were removed because they contained figures not found on the page."
        )

    combined_schema = build_combined_schema(ctx, article_schema, valid_questions)

    # 6. Warnings
    all_warnings = warnings + list(article_warnings)
    if total_removed_count > 0:
        all_warnings.append(
            f"{total_removed_count} suggestions were removed because they contained figures not found on the page."
        )

    if target_q:
        missing_lead_terms = get_missing_lead_query_terms(lead_paragraph_fix.suggested, target_q, lang)
        if missing_lead_terms:
            all_warnings.append(f"Suggested lead is missing target query term(s): {', '.join(missing_lead_terms)}")

    response_data = {
        "suggested_lead": lead_paragraph_fix.model_dump(),
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

    # 7. Store in cache (only if not failed due to DataForSEO error)
    if not serp_failed:
        put_ai_plan_cache(cache_key, response_data, now_ts + 86400)

    return AIPlanResponse(**response_data)


@app.post("/api/export/brief")
async def export_editor_brief(request: BriefExportRequest):
    """
    Generate and download an Editor Brief as a Word (.docx) document.
    Protected by access code like all /api/* routes.
    """
    try:
        docx_bytes = generate_editor_brief_docx(
            audit_result=request.audit_result,
            ai_fixes=request.ai_fixes,
            ai_plan=request.ai_plan,
            ahrefs_offpage=request.ahrefs_offpage,
        )
    except Exception as e:
        logger.error(f"Failed to generate improvement report .docx: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate improvement report document")

    domain = sanitize_domain_for_filename(request.audit_result.url)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"geo-report-{domain}-{date_str}.docx"

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.post("/api/ai/rewrite", response_model=AIRewriteResponse)
async def rewrite_article(request: AIRewriteRequest):
    """
    Generate complete draft article rewrite based on the audited page context and AI plan.
    Applies safety rules: preserves all original facts/legal phrases, flags invented figures,
    keeps [EDITOR: ...] placeholders, and removes meta-references/URLs.
    """
    current_settings = get_settings()
    if not current_settings.ai_enabled:
        raise HTTPException(status_code=503, detail="AI layer is not configured")

    ctx = request.ai_context
    plan = request.ai_plan

    llm = LLMClient()
    lang = ctx.language or "es"
    lang_instruction = "Spanish (Español)" if lang == "es" else "English"
    target_q = (request.target_query or ctx.target_query or "").strip()

    # Build prompt
    system_prompt = f"""You are a master editorial copywriter and search optimizer.
Your objective is to rewrite the full article into an exhaustive, highly citable web guide in Markdown.
The output must be strictly in {lang_instruction}.
Do NOT output explanations, introductory comments, or markdown fences. Output ONLY the raw Markdown article starting with the main # Title.

CRITICAL EDITORIAL & INTEGRITY RULES:
1. Keep all factual DATA from the original (figures, dates, names, facts), NOT all sentences. Each fact must appear only once in the body; in the FAQ it may be repeated briefly. Do not duplicate information across sections.
2. Only use facts present in the original page text snippet or the AI improvement plan. NEVER invent figures, statistics, dates, names, or quotes.
   - Do NOT add superlatives or rankings ("one of Italian football's most raucous atmospheres", "the best", "the largest", "the most iconic") if they are not explicitly present in the original text (e.g. if the original says "raucous atmosphere", write "raucous atmosphere", NOT "one of the most raucous").
   - Do NOT deduce or infer unstated facts from literal translations of foreign proper names (e.g. do not deduce "the covered main stand" from the name "Tribuna Copertura" without the original text stating it is covered or what kind of stand it is).
3. Plan paragraphs must be merged into the existing original paragraph discussing the same topic, rather than added as duplicate paragraphs next to it.
4. A new suggested H2 is only created if it provides information not already present in another section. If it only repeats another section, its content must be merged into that section and the H2 not created. Each suggested H2 must promise ONLY what the section actually contains; never introduce empty topics or features absent from the text (e.g. do NOT name a section "Layout and Roof Renovation" if the text does not discuss the roof or layout).
5. Target article length: around 1.5x original length + FAQ + genuinely new sections. Do not inflate word count with redundant phrasing.
6. When an FAQ question needs info or lacks data, the FIRST sentence must answer directly with the gap [EDITOR: description — source type] placed precisely where the missing data belongs (e.g. "Palermo FC's current ownership is [EDITOR: owner and stake — official club statements]."). When data is missing, the answer must NOT affirm or speculate on ANYTHING outside the gap: neither yes/no, nor that something exists or does not exist (e.g. do NOT say 'Club X is not owned by Y' or 'Tours operate [EDITOR]'). The gap must be right in the first sentence. Correct examples: "Palermo FC's current ownership is [EDITOR: owner and stake — official club statements]." and "[EDITOR: whether stadium tours are available, with days and prices — official club ticketing].". Preserve all [EDITOR: ...] placeholders already present in the AI plan.
7. NEVER invent first-person experience ("we tested", "we saw", "in our experience", "probamos", "visitamos"). If experience signals are needed, use: [EDITOR: add a real first-hand experience — team member who attended] in {lang_instruction}.
8. SENSITIVE TEXTS & TRADEMARKS INTACT: Any disclaimer, risk warning, "not financial advice", terms and conditions, volatility note, or regulatory compliance statement in the original text MUST BE COPIED LITERALLY and verbatim without modification. Never alter trademark symbols (™, ®, ©), brand names, or button/CTA texts. Inconsistencies that only affect trademark symbols or legal notices must NOT be modified: leave them as they are. Never offer financial advice or investment recommendations.
9. LINKS & CITATIONS: The user message lists ORIGINAL LINKS and ALLOWED EXTERNAL SOURCES. You MUST keep ALL original links as Markdown links [text](url), in the same context or as close as possible to where they were in the original. Keep button / CTA anchor texts verbatim. You may cite up to 3 allowed external sources, at most ONCE each, placed naturally on a short phrase within the sentence (2-6 words), e.g. "according to the [club's stadium guide](url)" or "[designs revealed by Populous](url)". NEVER use the title of the page as the anchor, NEVER enclose the link isolated inside parentheses like "([Title](url))", and NEVER use "..." or "…". NEVER place external links in Fan Token sections, legal/disclaimer texts, or FAQ. NEVER add any other URL. If no links are provided, write no URLs at all.
10. IMAGES: The user message lists the ORIGINAL IMAGES of the page. You MUST keep ALL of them as Markdown images ![alt](url), placed in the most appropriate section or as close as possible to their original position. Do NOT invent new images or alter the URLs. If the list is empty, include no images.
11. NO META-REFERENCES: Never refer to 'this page', 'the guide', 'this article', 'the post', 'la página', 'esta guía', 'este artículo', or similar meta-commentary. Write strictly as final web publication copy.
12. Structure, Inconsistencies & FAQ:
    - Begin with the # Main Title (H1).
    - Opening Lead Paragraph: Use the suggested lead paragraph from the plan. When a Target Query is provided, ensure the opening paragraph literally and naturally contains all its significant search terms (do not substitute with synonyms or foreign language equivalents; e.g. 'ground' or 'Stadio' do not satisfy 'stadium').
    - If inconsistencies / contradictions are listed, resolve them using the plan's recommendation and unify the terminology/value throughout the whole article (except trademark notation differences ™/®/©, which must be kept as they are).
    - Consistency: Always use the exact same term for the same role or entity throughout the whole article (e.g. do not mix "president" and "chairman"), even if the plan did not detect it. Do not repeat the exact same sentence across two different sections.
    - FAQ: Format each FAQ question as a subheading "### Question?" with the answer below (answers 2-3 sentences max). Retain the EXACT H2 and ALL original questions LITERALLY with their exact wording. At most 2 questions with [EDITOR: ...] gaps may be included, placed at the very end of the FAQ section.
    - Include the suggested comparison/data table formatted cleanly as a Markdown table with pipes.
    - Merge suggested actionable paragraphs into their appropriate sections.
"""

    plan_summary_parts = []
    if plan.suggested_lead and plan.suggested_lead.suggested:
        plan_summary_parts.append(f"SUGGESTED LEAD PARAGRAPH:\n{plan.suggested_lead.suggested}")

    if plan.suggested_h2_structure:
        h2_lines = [f"- {item.h2} (status: {item.status}) -> Purpose: {item.purpose}" for item in plan.suggested_h2_structure]
        plan_summary_parts.append("SUGGESTED H2 STRUCTURE:\n" + "\n".join(h2_lines))

    if plan.suggested_table and plan.suggested_table.headers and plan.suggested_table.rows:
        headers_str = " | ".join(plan.suggested_table.headers)
        rows_str = "\n".join([" | ".join(r) for r in plan.suggested_table.rows])
        plan_summary_parts.append(f"SUGGESTED TABLE:\nHeaders: {headers_str}\nRows:\n{rows_str}")

    if plan.questions_to_answer:
        q_lines = [f"- Q: {q.question}\n  A: {q.draft_answer} (source: {q.answer_source})" for q in plan.questions_to_answer]
        plan_summary_parts.append("QUESTIONS TO ANSWER (FAQ):\n" + "\n".join(q_lines))

    if plan.paragraphs_to_add:
        p_lines = [f"- Location: {p.placement}\n  Content: {p.suggested_text}" for p in plan.paragraphs_to_add]
        plan_summary_parts.append("NEW PARAGRAPHS TO INTEGRATE:\n" + "\n".join(p_lines))

    plan_context_text = "\n\n".join(plan_summary_parts)

    # External sources (up to 3 with why)
    valid_external_sources = [
        s for s in (plan.sources_to_cite or [])
        if getattr(s, "why", None) and s.why.strip() and getattr(s, "url", None)
    ][:3]

    original_links = extract_original_links(ctx.main_html or "", ctx.url)
    allowed_urls = {normalize_link_url(l["url"]) for l in original_links}

    original_images = extract_original_images(ctx.main_html or "", ctx.url)
    allowed_image_urls = {normalize_link_url(img["src"]) for img in original_images}
    allowed_urls.update(allowed_image_urls)

    allowed_ext_urls = {normalize_link_url(s.url): s for s in valid_external_sources}
    allowed_urls.update(allowed_ext_urls.keys())

    # Detect original FAQ
    orig_faq_h2, orig_faq_questions = extract_original_faq(ctx.main_html or "", ctx.main_text or "")

    if original_links:
        original_links_text = "\n".join(f"- [{l['text']}]({l['url']})" for l in original_links)
    else:
        original_links_text = "(none)"

    if valid_external_sources:
        external_sources_text = "\n".join(f"- [{s.title or s.domain}]({s.url}) — {s.why}" for s in valid_external_sources)
    else:
        external_sources_text = "(none)"

    if original_images:
        original_images_text = "\n".join(f"- ![{img['alt']}]({img['src']})" for img in original_images)
    else:
        original_images_text = "(none)"

    if orig_faq_h2:
        q_list_str = "\n".join(f"- {q}" for q in orig_faq_questions) if orig_faq_questions else "(none)"
        orig_faq_text = f"Heading: \"{orig_faq_h2}\"\nQuestions to preserve LITERALLY:\n{q_list_str}"
    else:
        orig_faq_text = "(none)"

    if plan.inconsistencies:
        incons_lines = [
            f"- {inc.issue} | Conflicting values: [{', '.join(inc.values)}] | Recommendation: {inc.suggestion}"
            for inc in plan.inconsistencies
        ]
        incons_text = "\n".join(incons_lines)
    else:
        incons_text = "(none)"

    user_prompt = f"""ORIGINAL ARTICLE METADATA:
Title: {ctx.title or 'N/A'}
H1: {ctx.h1 or 'N/A'}
Language: {lang_instruction}
Target Query: {target_q + ' (The opening paragraph MUST naturally and literally contain all its significant search terms; do not replace them with synonyms or foreign language translations)' if target_q else 'General content'}

ORIGINAL PAGE TEXT CONTENT:
{ctx.main_text}

ORIGINAL LINKS (keep ALL of them as Markdown links; add no other URLs):
{original_links_text}

ALLOWED EXTERNAL SOURCES TO CITE (cite at most once each, next to the fact they support; never in Fan Token, legal, or FAQ):
{external_sources_text}

ORIGINAL IMAGES (keep ALL of them as Markdown images ![alt](src); add no other images):
{original_images_text}

ORIGINAL FAQ TO PRESERVE:
{orig_faq_text}

INCONSISTENCIES TO RESOLVE:
{incons_text}

AI IMPROVEMENT PLAN TO APPLY:
{plan_context_text}

Write the complete rewritten article in Markdown now following all editorial and verification rules strictly in {lang_instruction}.
"""

    orig_text = ctx.main_text or ""
    orig_words = len(orig_text.split())

    # Build prompt payload
    url = f"{llm.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
    }
    rewrite_model = current_settings.llm_rewrite_model or llm.model
    rewrite_max_tokens = current_settings.llm_rewrite_max_tokens or 32000
    payload = {
        "model": rewrite_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": rewrite_max_tokens,
    }

    # Check and increment daily counter
    from src.services.llm_client import daily_tracker
    daily_tracker.check_and_increment(llm.daily_limit)

    timeout_config = httpx.Timeout(llm.timeout, read=60.0) if llm.streaming else httpx.Timeout(llm.timeout)

    max_attempts = 2
    final_content = ""
    final_finish_reason: Optional[str] = None
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=timeout_config) as http_client:
                if llm.streaming:
                    content, finish_reason = await llm._stream_and_extract_content(http_client, url, headers, payload)
                else:
                    content, finish_reason = await llm._post_and_extract_content(http_client, url, headers, payload)
        except DailyLimitExceededError as e:
            raise HTTPException(status_code=429, detail=str(e))
        except Exception as e:
            logger.error(f"LLM rewrite error on attempt {attempt}: {traceback.format_exc()}")
            if attempt < max_attempts:
                logger.warning(f"Retrying AI rewrite after error on attempt {attempt}...")
                await asyncio.sleep(1.0)
                continue
            raise HTTPException(status_code=502, detail=f"AI rewrite generation failed: {str(e)}")

        clean_content = content.strip()
        fence_m = re.match(r"^```(?:markdown)?\s*\n?([\s\S]*?)\n?```$", clean_content, re.I)
        if fence_m:
            clean_content = fence_m.group(1).strip()

        draft_words = len(clean_content.split())
        logger.info(
            f"AI rewrite attempt {attempt}/{max_attempts}: length={len(clean_content)} chars, "
            f"words={draft_words} (original={orig_words}), finish_reason={finish_reason}"
        )

        final_content = clean_content
        final_finish_reason = finish_reason

        is_empty = (not clean_content) or draft_words == 0
        is_under_50 = (orig_words > 0 and draft_words < orig_words * 0.5)
        is_length = (finish_reason == "length")

        if is_empty or is_under_50 or is_length:
            if attempt < max_attempts:
                logger.warning(
                    f"AI rewrite attempt {attempt} returned empty or incomplete draft "
                    f"(empty={is_empty}, words={draft_words}/{orig_words}, finish_reason={finish_reason}). "
                    f"Retrying once..."
                )
                await asyncio.sleep(1.0)
                continue

        break

    draft_words = len(final_content.split())
    is_empty = (not final_content) or draft_words == 0
    is_under_50 = (orig_words > 0 and draft_words < orig_words * 0.5)

    if is_empty or is_under_50:
        reason_str = final_finish_reason if final_finish_reason else "none"
        logger.error(
            f"AI rewrite failed quality check after attempt {attempt}: empty={is_empty}, "
            f"words={draft_words}/{orig_words}, finish_reason={reason_str}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"The AI returned an empty or incomplete draft (finish reason: {reason_str}). Please try again."
        )

    warnings: list[str] = []

    # If the draft finished due to length limit on attempt 2 (or kept), but exceeded 50%, add prominent warning
    if final_finish_reason == "length":
        warnings.append("The draft may be incomplete: the AI reached its length limit. Check the end of the article.")

    draft_markdown = final_content

    # 1. Verification of sensitive phrases (financial risk / disclaimers / T&C)
    # Detect sensitive sentences in original text and ensure they are literally present in the draft
    orig_text = ctx.main_text or ""
    orig_sentences = re.split(r'(?<=[.!?])\s+', orig_text)
    
    sens_keywords = SENSITIVE_LEGAL_KEYWORDS.get(lang if lang in ("en", "es") else "en", SENSITIVE_LEGAL_KEYWORDS["en"])
    missing_sensitive: list[str] = []

    for s in orig_sentences:
        s_clean = s.strip()
        if len(s_clean) < 15:
            continue
        s_lower = s_clean.lower()
        if any(kw in s_lower for kw in sens_keywords):
            # Check if this sentence appears in draft_markdown (case-insensitive or partial)
            s_clean_norm = re.sub(r'[^\w\s]', '', s_clean.lower())
            draft_norm = re.sub(r'[^\w\s]', '', draft_markdown.lower())
            if s_clean_norm not in draft_norm:
                missing_sensitive.append(s_clean)

    if missing_sensitive:
        draft_markdown += "\n\n" + " ".join(missing_sensitive)
        for ms in missing_sensitive:
            warnings.append(f"Restored required sensitive legal disclaimer: \"{ms[:80]}...\"")

    # 2. Verification of figures / numbers
    plan_full_text = plan_context_text
    num_pattern = re.compile(r'\b(?:\d{1,3}(?:[,\.]\d{3})*|\d+)(?:[,\.]\d+)?%?\b')
    ext_source_urls = [s.url for s in valid_external_sources]
    orig_and_plan_numbers = set(
        num_pattern.findall(
            orig_text
            + " "
            + plan_full_text
            + " "
            + " ".join(l["url"] for l in original_links)
            + " "
            + " ".join(img["src"] for img in original_images)
            + " "
            + " ".join(ext_source_urls)
        )
    )

    def _check_and_mark_figures(md_text: str) -> tuple[str, list[str]]:
        flagged_warnings = []
        lines = md_text.split("\n")
        new_lines = []
        for line in lines:
            # Skip heading lines, table borders, or image lines
            if line.strip().startswith("#") or line.strip().startswith("|---") or line.strip().startswith("!["):
                new_lines.append(line)
                continue
            
            # Split line into sentences
            parts = re.split(r'(?<=[.!?])\s+', line)
            new_parts = []
            for part in parts:
                p_clean = part.strip()
                if not p_clean:
                    new_parts.append(part)
                    continue
                # If part already has an editor tag, skip
                if "[EDITOR:" in p_clean:
                    new_parts.append(part)
                    continue
                
                # Check figures in part
                figs = num_pattern.findall(p_clean)
                unverified_figs = [f for f in figs if f not in orig_and_plan_numbers and len(f) > 1 and not re.match(r'^(?:19\d\d|20\d\d)$', f)]
                if unverified_figs:
                    flag_note = f" [EDITOR: verify this figure ({', '.join(unverified_figs)}) — not in the original page]"
                    new_parts.append(part + flag_note)
                    flagged_warnings.append(f"Unverified figure detected ({', '.join(unverified_figs)}) — editor verification flag added.")
                else:
                    new_parts.append(part)
            new_lines.append(" ".join(new_parts))
        return "\n".join(new_lines), flagged_warnings

    draft_markdown, fig_warnings = _check_and_mark_figures(draft_markdown)
    warnings.extend(fig_warnings)

    # 3. Apply URL filtering and external sources enforcement
    # Protect editor gaps before running filters
    gaps: list[str] = []
    def _gap_stash(m: re.Match) -> str:
        gaps.append(m.group(0))
        return f"___EDITOR_GAP_PRESERVE_{len(gaps)-1}___"

    stashed = re.sub(r'\[EDITOR:[^\]]*\]', _gap_stash, draft_markdown)

    seen_ext_urls = set()
    current_section = ""
    is_fan_token_section = False
    is_legal_section = False
    is_faq_section = False

    FAN_TOKEN_RE = re.compile(r'(?i)\bfan\s*tokens?[\u2122\xae\xa9]?', re.I)
    sens_kws = list(SENSITIVE_LEGAL_KEYWORDS.get("en", [])) + list(SENSITIVE_LEGAL_KEYWORDS.get("es", []))

    raw_blocks = re.split(r'(\n\s*\n)', stashed)
    processed_blocks = []

    for block in raw_blocks:
        if not block.strip():
            processed_blocks.append(block)
            continue

        # Check headings inside block
        for line in block.split("\n"):
            line_s = line.strip()
            if line_s.startswith("#"):
                current_section = line_s.lower()
                is_fan_token_section = bool(re.search(r'(?i)\bfan\s*tokens?[\u2122\xae\xa9]?|\$|\btoken\b', current_section))
                is_legal_section = bool(re.search(r'(?i)\b(?:disclaimer|terms|risk|legal|aviso\s+legal)\b', current_section))
                is_faq_section = bool(re.search(r'\b(?:faq|faqs|frequently\s+asked\s+questions|preguntas\s+frecuentes)\b', current_section)) or (
                    orig_faq_h2 is not None and normalize_heading(orig_faq_h2) in normalize_heading(current_section)
                )

        # Paragraph-level check: contains "fan token" (any form) or any word from SENSITIVE_LEGAL_KEYWORDS
        block_lower = block.lower()
        has_fan_token = bool(FAN_TOKEN_RE.search(block))
        has_legal_kw = any(kw in block_lower for kw in sens_kws)
        is_prohibited_para = is_fan_token_section or is_legal_section or is_faq_section or has_fan_token or has_legal_kw

        # Convert external source links in prohibited sections or paragraphs (or if already seen) into plain anchor text
        def _check_ext_link(m: re.Match) -> str:
            anchor = m.group(1)
            u = m.group(2)
            u_norm = normalize_link_url(u)
            if u_norm in allowed_ext_urls:
                if is_prohibited_para:
                    return anchor
                if u_norm in seen_ext_urls:
                    return anchor
                seen_ext_urls.add(u_norm)
            return m.group(0)

        block_with_ext = _MD_LINK_RE.sub(_check_ext_link, block)

        new_lines = []
        for line in block_with_ext.split("\n"):
            line_s = line.strip()
            if not line_s:
                new_lines.append(line)
            elif line_s.startswith("#") or line_s.startswith("|") or line_s.startswith("!["):
                new_lines.append(filter_draft_urls(line, allowed_urls))
            else:
                l_clean = filter_draft_urls(line, allowed_urls)
                l_clean = strip_page_meta_references(l_clean)
                if l_clean.strip():
                    new_lines.append(l_clean)

        processed_blocks.append("\n".join(new_lines))

    stashed = "".join(processed_blocks)

    for idx, gap in enumerate(gaps):
        stashed = stashed.replace(f"___EDITOR_GAP_PRESERVE_{idx}___", gap)

    draft_markdown = stashed.strip()

    # Standalone link anchor text restoration
    # If a line in draft_markdown contains solely a Markdown link whose URL matches an original link,
    # restore the exact original anchor text.
    orig_anchor_by_url = {
        normalize_link_url(l["url"]): l["text"]
        for l in (original_links or []) if l.get("text") and l.get("url")
    }
    restored_lines = []
    for line in draft_markdown.split("\n"):
        line_s = line.strip()
        btn_m = re.match(r'^(?:[\*\-\+]\s+|\d+\.\s+)?\[([^\]]+)\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)\s*$', line_s)
        if btn_m:
            curr_anchor = btn_m.group(1)
            url_target = btn_m.group(2)
            u_norm = normalize_link_url(url_target)
            if u_norm in orig_anchor_by_url:
                orig_anc = orig_anchor_by_url[u_norm]
                old_target = f"[{curr_anchor}]("
                new_target = f"[{orig_anc}]("
                line = line.replace(old_target, new_target, 1)
        restored_lines.append(line)
    draft_markdown = "\n".join(restored_lines)

    # 4. Warn about original links that did not make it into the draft
    draft_urls = {
        normalize_link_url(u)
        for u in re.findall(r'https?://[^\s)\]]+', draft_markdown)
    }
    if original_links:
        for l in original_links:
            if normalize_link_url(l["url"]) not in draft_urls:
                warnings.append(f"Original link not preserved: {l['text']} ({l['url']})")

    # 5. Warn about original images that did not make it into the draft
    if original_images:
        draft_image_urls = {
            normalize_link_url(m.group(2))
            for m in _MD_IMG_RE.finditer(draft_markdown)
        }
        for img in original_images:
            if normalize_link_url(img["src"]) not in draft_image_urls:
                alt_desc = img["alt"] if img["alt"] else "unnamed image"
                warnings.append(f"Original image not preserved: {alt_desc} ({img['src']})")

    # 6. Warn about external sources added to the draft and check citation formatting
    for s in valid_external_sources:
        s_norm = normalize_link_url(s.url)
        if s_norm in draft_urls:
            dom = s.domain or urllib.parse.urlparse(s.url).netloc
            warnings.append(f"External source added: {dom} — check that it supports the claim next to it")
            for m in _MD_LINK_RE.finditer(draft_markdown):
                if normalize_link_url(m.group(2)) == s_norm:
                    anchor = m.group(1).strip()
                    full_link = m.group(0)
                    is_ellipsis = anchor.endswith("...") or anchor.endswith("…")
                    is_in_parens = bool(re.search(r'\(\s*' + re.escape(full_link) + r'\s*\)', draft_markdown))
                    if is_ellipsis or is_in_parens:
                        warnings.append(f"Citation anchor looks like a page title: {anchor}")

    # 7. Check for duplicated content (content-word set overlap before FAQ)
    body_for_dupes = draft_markdown
    faq_match = re.search(r'(?mi)^##\s+.*(?:faq|faqs|frequently\s+asked\s+questions|preguntas\s+frecuentes).*$', draft_markdown)
    if not faq_match and orig_faq_h2:
        faq_match = re.search(r'(?mi)^##\s+' + re.escape(orig_faq_h2) + r'$', draft_markdown)
    if faq_match:
        body_for_dupes = draft_markdown[:faq_match.start()]

    raw_paras = [p.strip() for p in re.split(r'\n\s*\n', body_for_dupes) if p.strip()]
    candidate_paras: list[str] = []
    para_word_sets: list[set[str]] = []

    for p in raw_paras:
        if p.startswith("#") or p.startswith("|") or p.startswith("!["):
            continue
        p_no_gaps = re.sub(r'\[EDITOR:[^\]]*\]', '', p).strip()
        # Exclude paragraphs that are solely a single link or button
        if re.match(r'^(?:[\*\-\+]\s+|\d+\.\s+)?\[[^\]]+\]\([^)]+\)\s*$', p_no_gaps):
            continue

        # Replace markdown images and links with alt/anchor text, remove loose URLs and editor gaps
        p_clean = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', p_no_gaps)
        p_clean = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', p_clean)
        p_clean = re.sub(r'https?://[^\s)\]]+', '', p_clean)

        # Content words of more than 2 letters without stop words
        words = re.findall(r'\b[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]{3,}\b', p_clean.lower())
        cwords = set(w for w in words if w not in EN_ES_STOP_WORDS)
        # Exclude paragraphs with fewer than 8 content words
        if len(cwords) < 8:
            continue
        candidate_paras.append(p)
        para_word_sets.append(cwords)

    # Remove words appearing in >= 50% of candidate body paragraphs (entity names like "stadio", "renzo", "barbera", "palermo")
    word_doc_freq: dict[str, int] = {}
    for wset in para_word_sets:
        for w in wset:
            word_doc_freq[w] = word_doc_freq.get(w, 0) + 1

    num_body_paras = len(candidate_paras)
    if num_body_paras >= 3:
        frequent_words = {
            w for w, count in word_doc_freq.items()
            if count >= 3 and count >= num_body_paras * 0.5
        }
    else:
        frequent_words = set()

    filtered_para_sets = [wset - frequent_words for wset in para_word_sets]

    seen_dupe_pairs = set()
    for i in range(num_body_paras):
        set_a = filtered_para_sets[i]
        for j in range(i + 1, num_body_paras):
            set_b = filtered_para_sets[j]
            if len(set_a) >= 8 and len(set_b) >= 8:
                overlap = len(set_a & set_b)
                denom = min(len(set_a), len(set_b))
                if denom > 0 and (overlap / denom) >= 0.45:
                    pair_key = (min(i, j), max(i, j))
                    if pair_key not in seen_dupe_pairs:
                        seen_dupe_pairs.add(pair_key)
                        snip_a = " ".join(candidate_paras[i].split()[:8])
                        snip_b = " ".join(candidate_paras[j].split()[:8])
                        warnings.append(f"Possible duplicated content: '{snip_a}…' / '{snip_b}…'")

    # 8. Check for original figures missing from draft
    orig_figs = num_pattern.findall(orig_text)
    unique_orig_figs = []
    seen_ofigs = set()
    for f in orig_figs:
        if f not in seen_ofigs:
            seen_ofigs.add(f)
            unique_orig_figs.append(f)

    draft_figs = set(num_pattern.findall(draft_markdown))
    for f in unique_orig_figs:
        f_norm = f.replace(",", "").replace(".", "")
        if f not in draft_figs and f not in draft_markdown and f_norm not in draft_markdown:
            warnings.append(f"Original figure missing from draft: {f}")

    # 9. Check for unresolved inconsistencies (normalized to handle punctuation & quotes)
    TM_SYMBOLS_RE = re.compile(r'[\u2122\xae\xa9]')
    draft_norm_incons = normalize_heading(draft_markdown)
    for inc in (plan.inconsistencies or []):
        if inc.values and len(inc.values) >= 2:
            val_stripped_set = {normalize_heading(TM_SYMBOLS_RE.sub('', v)) for v in inc.values}
            if len(val_stripped_set) == 1 and len(set(inc.values)) > 1:
                tm_warn = "Trademark notation differs (™ vs ®) — check with legal, not changed by the AI"
                if tm_warn not in warnings:
                    warnings.append(tm_warn)
                continue

            all_present = True
            for val in inc.values:
                val_norm = normalize_heading(val)
                if not val_norm or val_norm not in draft_norm_incons:
                    all_present = False
                    break
            if all_present:
                warnings.append(f"Inconsistency not resolved: {inc.issue}")

    # 10. Process and rebuild FAQ section (deduplication, max 2 editor gaps, format with ###)
    faq_match = re.search(r'(?mi)^##\s+.*(?:faq|faqs|frequently\s+asked\s+questions|preguntas\s+frecuentes).*$', draft_markdown)
    if not faq_match and orig_faq_h2:
        faq_match = re.search(r'(?mi)^##\s+' + re.escape(orig_faq_h2) + r'$', draft_markdown)

    if faq_match:
        faq_start = faq_match.start()
        faq_header_line = draft_markdown[faq_start:draft_markdown.find("\n", faq_start) if "\n" in draft_markdown[faq_start:] else len(draft_markdown)]
        after_match = draft_markdown[faq_match.end():]
        next_h2 = re.search(r'(?mi)^##\s+(?!#)', after_match)
        if next_h2:
            faq_end = faq_match.end() + next_h2.start()
            after_faq = draft_markdown[faq_end:]
        else:
            faq_end = len(draft_markdown)
            after_faq = ""
        before_faq = draft_markdown[:faq_start]
        faq_full = draft_markdown[faq_start:faq_end]

        faq_inner = faq_full[len(faq_header_line):]
        blocks = re.split(r'(?m)^(?=###\s+|Q:\s*|\*\*\s*Q:\s*|\*\*(?:Q:\s*)?[^\n]+\?\*\*)', faq_inner)
        intro_text = blocks[0].strip() if blocks else ""

        orig_norm_set = {normalize_heading(q) for q in orig_faq_questions}
        paa_norm_set = set()
        paa_words_list: list[set[str]] = []
        for pq in (plan.questions_to_answer or []):
            is_paa = (getattr(pq, "origin", None) == "google_paa" or getattr(pq, "answer_source", None) in ("paa", "organic", "google_paa"))
            if is_paa and pq.question:
                paa_norm_set.add(normalize_heading(pq.question))
                pw = set(w for w in re.findall(r'\b[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]{3,}\b', pq.question.lower()) if w not in EN_ES_STOP_WORDS)
                if pw:
                    paa_words_list.append(pw)

        def _clean_faq_q(q: str) -> str:
            q = re.sub(r'^(?:###\s*|(?:\*|\s)*(?:Q|Question)(?:\*\*|\*|\s)*:\s*|\*+|\s+)+', '', q, flags=re.IGNORECASE).strip()
            q = re.sub(r'[\*#:\s]+$', '', q).strip()
            return q

        def _clean_faq_rem(a: str) -> str:
            a = re.sub(r'^(?:\*|\s)*(?:\*\*|\*|\s)*(?:A|Answer)(?:\*\*|\*|\s)*:\s*(?:\*\*|\*|\s)*', '', a, flags=re.IGNORECASE).strip()
            a = re.sub(r'^(?:\*|\s)+', '', a).strip()
            return a

        def _clean_faq_next_line(a: str) -> str:
            a = re.sub(r'^(?:\*\*|\*|\s)*(?:A|Answer)(?:\*\*|\*|\s)*:\s*(?:\*\*|\*|\s)*', '', a, flags=re.IGNORECASE).strip()
            return a

        class _ParsedFAQ:
            def __init__(self, raw_block: str):
                lines = raw_block.strip().split("\n")
                first_line = lines[0].strip()
                rest_lines = lines[1:]

                q_idx = first_line.find("?")
                if q_idx != -1:
                    q_raw = first_line[:q_idx + 1]
                    rem_raw = first_line[q_idx + 1:].strip()
                else:
                    m_bold = re.match(r'^\*\*(.*?)\*\*\s*(.*)$', first_line)
                    if m_bold:
                        q_raw = m_bold.group(1)
                        rem_raw = m_bold.group(2).strip()
                    else:
                        m_h3 = re.match(r'^###\s+(.*)$', first_line)
                        if m_h3:
                            q_raw = m_h3.group(1)
                            rem_raw = ""
                        else:
                            q_raw = first_line
                            rem_raw = ""

                self.question = _clean_faq_q(q_raw)
                ans_parts: list[str] = []
                if rem_raw:
                    clean_rem = _clean_faq_rem(rem_raw)
                    if clean_rem:
                        ans_parts.append(clean_rem)
                if rest_lines:
                    if not ans_parts:
                        clean_first_rest = _clean_faq_next_line(rest_lines[0])
                        if clean_first_rest:
                            ans_parts.append(clean_first_rest)
                        ans_parts.extend(rest_lines[1:])
                    else:
                        ans_parts.extend(rest_lines)

                self.answer_text = "\n".join(ans_parts).strip()
                self.is_original = normalize_heading(self.question) in orig_norm_set

                # Content words of the FAQ item (question + answer) for robust deduplication
                full_item_text = self.question + " " + self.answer_text
                words = re.findall(r'\b[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]{3,}\b', full_item_text.lower())
                self.content_words = set(w for w in words if w not in EN_ES_STOP_WORDS)
                self.has_gap = "[EDITOR:" in self.answer_text

                # Check PAA priority
                q_norm = normalize_heading(self.question)
                matched_paa = q_norm in paa_norm_set
                if not matched_paa and self.content_words:
                    q_words = set(w for w in re.findall(r'\b[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]{3,}\b', self.question.lower()) if w not in EN_ES_STOP_WORDS)
                    for pw in paa_words_list:
                        denom = min(len(q_words), len(pw)) if q_words else 0
                        if denom > 0 and (len(q_words & pw) / denom) >= 0.60:
                            matched_paa = True
                            break
                self.is_paa = matched_paa

        parsed_items = [_ParsedFAQ(b) for b in blocks[1:] if b.strip()]

        # 1. Deduplicate questions sharing >= 60% of content words
        kept_items: list[_ParsedFAQ] = []
        for item in parsed_items:
            dupe_idx = None
            for idx, kept in enumerate(kept_items):
                wa = kept.content_words
                wb = item.content_words
                if wa and wb:
                    denom = min(len(wa), len(wb))
                    if denom > 0 and (len(wa & wb) / denom) >= 0.60:
                        dupe_idx = idx
                        break
            if dupe_idx is not None:
                kept = kept_items[dupe_idx]
                if item.is_original and not kept.is_original:
                    removed = kept
                    kept_items[dupe_idx] = item
                    warnings.append(f"Duplicate FAQ question removed: {removed.question}")
                else:
                    warnings.append(f"Duplicate FAQ question removed: {item.question}")
            else:
                kept_items.append(item)

        # 2. Limit questions with [EDITOR: ...] gaps to max 2, prioritizing PAA
        gap_items = [it for it in kept_items if it.has_gap]
        if len(gap_items) > 2:
            sorted_gaps = sorted(gap_items, key=lambda it: (0 if it.is_paa else 1))
            to_keep_gaps = set(sorted_gaps[:2])
            to_remove_gaps = sorted_gaps[2:]
            for rem in to_remove_gaps:
                warnings.append(f"Suggested FAQ question not included (needs data): {rem.question}")
            kept_items = [it for it in kept_items if not it.has_gap or it in to_keep_gaps]

        # 3. Partition: non-gap questions first, followed by at most 2 gap questions at the end
        non_gap_items = [it for it in kept_items if not it.has_gap]
        final_gap_items = [it for it in kept_items if it.has_gap]

        # 4. Check unsupported claims before editor gap in first sentence & emit gap warning
        for it in final_gap_items:
            m_sent = re.search(r'^(.*?[.!?])(?:\s+|$)', it.answer_text.strip(), flags=re.DOTALL)
            first_sentence = m_sent.group(1).strip() if m_sent else it.answer_text.strip()
            if "[EDITOR:" not in first_sentence:
                warnings.append(f"Possible unsupported claim before the editor gap: {first_sentence}")
            warnings.append(f"FAQ with editor gap: {it.question} — fill it or remove it before publishing")

        # 5. Reconstruct FAQ markdown with ### headings
        faq_sections: list[str] = []
        if intro_text:
            faq_sections.append(intro_text)
        for it in non_gap_items + final_gap_items:
            faq_sections.append(f"### {it.question}\n\n{it.answer_text}")

        reconstructed_faq = faq_header_line + "\n\n" + "\n\n".join(faq_sections) + ("\n\n" if after_faq else "\n")
        draft_markdown = before_faq + reconstructed_faq + after_faq

    # 11. Check for dropped original FAQ questions
    draft_norm_headings = normalize_heading(draft_markdown)
    for q in orig_faq_questions:
        q_norm = normalize_heading(q)
        if q_norm and q_norm not in draft_norm_headings:
            warnings.append(f"Original FAQ question dropped: {q}")

    # 12. Check for missing target query terms in opening paragraph
    if target_q:
        draft_lead = extract_draft_opening_paragraph(draft_markdown)
        missing_lead_terms = get_missing_lead_query_terms(draft_lead, target_q, lang)
        if missing_lead_terms:
            warnings.append(f"Draft opening paragraph is missing target query term(s): {', '.join(missing_lead_terms)}")

    word_count_original = len(orig_text.split())
    word_count_draft = len(draft_markdown.split())

    return AIRewriteResponse(
        draft_markdown=draft_markdown,
        warnings=warnings,
        word_count_original=word_count_original,
        word_count_draft=word_count_draft,
    )


@app.post("/api/ai/rewrite/score", response_model=AIRewriteScoreResponse)
async def score_rewrite_comparison(request: AIRewriteScoreRequest):
    """
    Fair content-only audit comparison between original HTML and rewritten draft Markdown.
    Excludes whole-page technical and metadata dimensions (technical_infrastructure, metadata_schema, freshness, eeat_authority)
    and renormalizes scores across active content dimensions.
    """
    import markdown
    draft_html = markdown.markdown(request.draft_markdown, extensions=['tables', 'fenced_code'])

    # Audit both using content_html
    orig_req = AuditRequest(content_html=request.original_html, target_query=request.target_query)
    draft_req = AuditRequest(content_html=draft_html, target_query=request.target_query)

    orig_audit = await run_single_audit(
        orig_req,
        scraper,
        scrape_semaphore,
        fetch_robots_fn=fetch_robots_txt,
        measure_ttfb_fn=measure_ttfb
    )
    draft_audit = await run_single_audit(
        draft_req,
        scraper,
        scrape_semaphore,
        fetch_robots_fn=fetch_robots_txt,
        measure_ttfb_fn=measure_ttfb
    )

    # Dimensions to exclude: technical_infrastructure, metadata_schema, freshness, eeat_authority
    # technical_infrastructure: depends on server TTFB, HTTP headers, robots.txt, SSL.
    # metadata_schema: depends on <head> title, meta tags, and JSON-LD schema.
    # freshness: depends on article meta dates and ISO time tags not in content body.
    # eeat_authority: author bios and publisher credentials reside in site template / author pages, not article content body.
    EXCLUDED_DIMENSIONS = {
        "technical_infrastructure",
        "metadata_schema",
        "freshness",
        "eeat_authority",
    }

    orig_dims = {d.name: d for d in orig_audit.dimensions}
    draft_dims = {d.name: d for d in draft_audit.dimensions}

    # Filter dimensions
    included_names = [d.name for d in orig_audit.dimensions if d.name not in EXCLUDED_DIMENSIONS and d.name in draft_dims]

    comp_list: list[DimensionScoreComparison] = []
    weight_sum = 0.0
    weighted_orig_sum = 0.0
    weighted_draft_sum = 0.0

    for name in included_names:
        od = orig_dims[name]
        dd = draft_dims[name]
        diff = round(dd.score - od.score, 1)
        comp_list.append(DimensionScoreComparison(
            name=name,
            score_before=round(od.score, 1),
            score_after=round(dd.score, 1),
            difference=diff,
        ))
        w = od.weight
        weight_sum += w
        weighted_orig_sum += (od.score * w)
        weighted_draft_sum += (dd.score * w)

    if weight_sum > 0:
        total_before = round(weighted_orig_sum / weight_sum, 1)
        total_after = round(weighted_draft_sum / weight_sum, 1)
    else:
        total_before = 0.0
        total_after = 0.0

    total_diff = round(total_after - total_before, 1)

    return AIRewriteScoreResponse(
        total_score_before=total_before,
        total_score_after=total_after,
        difference=total_diff,
        dimensions=comp_list,
        excluded_dimensions=sorted(list(EXCLUDED_DIMENSIONS)),
    )


@app.post("/api/export/rewrite")
async def export_rewrite_draft_endpoint(request: RewriteBriefExportRequest):
    """
    Generate and download the AI article rewrite draft as a Word (.docx) document.
    """
    try:
        docx_bytes = generate_rewrite_draft_docx(
            url=request.url,
            draft_markdown=request.draft_markdown,
            warnings=request.warnings,
            score_comparison=request.score_comparison,
        )
    except Exception as e:
        logger.error(f"Failed to generate rewrite draft .docx: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate rewrite draft document")

    domain = sanitize_domain_for_filename(request.url or "manual-input")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"rewrite-{domain}-{date_str}.docx"

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.post("/api/offpage", response_model=AhrefsOffpageResponse)
async def get_offpage_signals(request: AhrefsOffpageRequest):
    """
    Fetch off-page authority and ranking signals from Ahrefs API v3.
    Protected by access code. Results do not affect the Citation Score.
    """
    s = get_settings()
    if not s.ahrefs_enabled:
        raise HTTPException(status_code=503, detail="Ahrefs is not configured")

    if not request.url or not request.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    url = request.url.strip()

    # 1. Check in-memory 7-day cache
    cached_data = get_cached_ahrefs_data(url)
    if cached_data:
        recs = generate_ahrefs_recommendations(
            referring_domains=cached_data.get("referring_domains"),
            organic_keywords=cached_data.get("organic_keywords"),
            top3_keywords=cached_data.get("top3_keywords"),
            url_rating=cached_data.get("url_rating"),
            domain_rating=cached_data.get("domain_rating"),
            language=request.language or "en",
            linking_pages=cached_data.get("linking_pages"),
        )
        return AhrefsOffpageResponse(
            **cached_data,
            recommendations=recs,
        )

    # 2. Check daily limit
    daily_count = get_ahrefs_daily_count()
    if daily_count >= s.ahrefs_daily_limit:
        raise HTTPException(status_code=429, detail="Daily Ahrefs limit reached, try again tomorrow")

    # 3. Call Ahrefs client
    client = AhrefsClient(api_key=s.ahrefs_api_key)
    try:
        signals = await client.fetch_offpage_signals(url)
    except AhrefsAuthError:
        raise HTTPException(status_code=503, detail="Ahrefs rejected the API key. Check GEO_AUDITOR_AHREFS_API_KEY.")
    except ValueError:
        raise HTTPException(status_code=503, detail="Ahrefs is not configured")
    except Exception as e:
        logger.error(f"Failed to fetch Ahrefs off-page signals: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="Failed to fetch Ahrefs data")

    # Check if all metrics are null (failed requests)
    metric_keys = [
        "domain_rating",
        "url_rating",
        "referring_domains",
        "backlinks",
        "referring_domains_all_time",
        "organic_keywords",
        "top3_keywords",
        "organic_traffic",
    ]
    if not any(signals.get(k) is not None for k in metric_keys) and signals.get("linking_pages") is None:
        raise HTTPException(status_code=502, detail="Ahrefs returned no data. Try again later.")

    # Increment daily count and cache only when response contains valid data
    increment_ahrefs_daily_count()
    put_cached_ahrefs_data(url, signals)

    # Generate rule-based recommendations
    recs = generate_ahrefs_recommendations(
        referring_domains=signals.get("referring_domains"),
        organic_keywords=signals.get("organic_keywords"),
        top3_keywords=signals.get("top3_keywords"),
        url_rating=signals.get("url_rating"),
        domain_rating=signals.get("domain_rating"),
        language=request.language or "en",
        linking_pages=signals.get("linking_pages"),
    )

    return AhrefsOffpageResponse(
        **signals,
        recommendations=recs,
    )




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
