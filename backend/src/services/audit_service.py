"""
GEO-AUDITOR AI - Core Audit Service

Extracts audit logic into a reusable pipeline function that can be called
by both single audit endpoint (/api/audit) and batch audit worker.
"""

import time
import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse
import httpx

from config.settings import get_settings
from src.models.schemas import (
    AuditRequest,
    AuditResponse,
    DimensionScore,
    PageData,
    AIContext,
    FailingSubmetric,
)
from src.scrapers.base_scraper import ScraperError, ChallengePageError
from src.utils.challenge_detection import is_challenge_page
from src.detectors.infrastructure import InfrastructureDetector
from src.detectors.evidence_density import EvidenceDensityDetector
from src.utils.lang_patterns import detect_language
from src.utils.content_type import detect_content_type

logger = logging.getLogger("geo_auditor")


async def _measure_single_ttfb(url: str, headers: dict) -> Optional[float]:
    """Single TTFB measurement with dedicated client including full connection."""
    try:
        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                return (time.perf_counter() - start_time) * 1000
    except Exception:
        return None


async def measure_ttfb(url: str) -> Tuple[Optional[float], Optional[list[float]]]:
    """
    Measure Time To First Byte (TTFB) 3 times sequentially with fresh connections and return (median_ttfb, samples).
    """
    if not url or not url.startswith(("http://", "https://")):
        return None, None
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": user_agent}
    samples: list[float] = []
    try:
        for _ in range(3):
            sample = await _measure_single_ttfb(url, headers)
            if sample is not None:
                samples.append(sample)
        if not samples:
            return None, None
        import statistics
        median_val = statistics.median(samples)
        return median_val, samples
    except Exception as e:
        logger.warning(f"TTFB measurement failed for {url}: {e}")
        return None, None


async def fetch_robots_txt(url: str) -> Optional[str]:
    """
    Fetch /robots.txt with httpx (timeout 5s).
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        headers = {"User-Agent": user_agent}
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(robots_url, headers=headers)
            if resp.status_code == 200:
                return resp.text
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch robots.txt for {url}: {e}")
        return None


async def run_single_audit(
    request: AuditRequest,
    scraper,
    scrape_semaphore: asyncio.Semaphore,
    fetch_robots_fn=None,
    measure_ttfb_fn=None
) -> AuditResponse:
    """
    Execute a full audit on the given request using the provided scraper and concurrency semaphore.
    Raises ScraperError or RuntimeError on failure.
    """
    settings = get_settings()
    start_time = time.time()
    url = str(request.url) if request.url else "text-mode"

    # Step 1: Acquisition (Scrape or use provided text)
    if request.content_text:
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
            is_ssr=True,
            is_https=True,
            ttfb_ms=None,
            robots_txt_content=None
        )
    elif request.url:
        async with scrape_semaphore:
            effective_measure_ttfb = measure_ttfb_fn or measure_ttfb
            effective_fetch_robots = fetch_robots_fn or fetch_robots_txt

            ttfb_task = effective_measure_ttfb(request.url)
            scrape_task = scraper.scrape(request.url)
            ttfb_res, page_data = await asyncio.gather(ttfb_task, scrape_task)
            if isinstance(ttfb_res, tuple) and len(ttfb_res) == 2:
                ttfb_median, ttfb_samples = ttfb_res
            elif isinstance(ttfb_res, (int, float)):
                ttfb_median, ttfb_samples = float(ttfb_res), [float(ttfb_res)]
            else:
                ttfb_median, ttfb_samples = None, None
            page_data.ttfb_ms = ttfb_median
            page_data.ttfb_samples = ttfb_samples
            target_url_for_robots = page_data.final_url or request.url
            page_data.robots_txt_content = await effective_fetch_robots(target_url_for_robots)
    else:
        raise ValueError("Must provide either URL or content_text")

    # Anti-bot challenge verification: a challenge page must never be scored
    if not request.content_text and is_challenge_page(
        text=page_data.text_content,
        html=page_data.html_rendered,
        status_code=page_data.status_code
    ):
        raise ChallengePageError(url=str(page_data.url or request.url))

    # Step 1.5: Language & Content Type Detection
    detected_lang = detect_language(page_data.text_content)
    page_data.language = detected_lang
    content_type = detect_content_type(page_data)
    page_data.content_type = content_type

    # Step 2: Run detectors
    detector_results = []
    all_recommendations = []

    # --- Layer 1: Technical Infrastructure (10%) ---
    if not request.content_text:
        try:
            infra_detector = InfrastructureDetector()
            infra_result = await infra_detector.analyze(page_data)
            detector_results.append(infra_result)
            for breakdown in infra_result.breakdown:
                all_recommendations.extend(breakdown.recommendations)
        except Exception as e:
            logger.error(f"Infrastructure detector error: {e}")

    # --- Layer 2: Metadata (4%) ---
    try:
        from src.detectors.metadata import MetadataDetector
        metadata_detector = MetadataDetector()
        metadata_result = await metadata_detector.analyze(page_data)
        detector_results.append(metadata_result)
        for breakdown in metadata_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Metadata detector error: {e}")

    # --- Layer 3: AEO Structure (12%) ---
    try:
        from src.detectors.aeo_structure import AEOStructureDetector
        aeo_detector = AEOStructureDetector()
        aeo_result = await aeo_detector.analyze(page_data)
        detector_results.append(aeo_result)
        for breakdown in aeo_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"AEO Structure detector error: {e}")

    # --- Layer 6: Entity Identification (6%) ---
    try:
        from src.detectors.entity import EntityDetector
        entity_detector = EntityDetector()
        entity_result = await entity_detector.analyze(page_data)
        detector_results.append(entity_result)
        for breakdown in entity_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Entity detector error: {e}")

    # --- Layer 4: Evidence Mapping (18%) ---
    try:
        evidence_detector = EvidenceDensityDetector()
        evidence_result = await evidence_detector.analyze(page_data)
        detector_results.append(evidence_result)
        for breakdown in evidence_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Evidence detector error: {e}")

    # --- Layer 5: E-E-A-T Authority (12%) ---
    try:
        from src.detectors.authority import AuthorityDetector
        authority_detector = AuthorityDetector()
        authority_result = await authority_detector.analyze(page_data)
        detector_results.append(authority_result)
        for breakdown in authority_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Authority detector error: {e}")

    # --- Layer 8: Formatting & UX (6%) ---
    try:
        from src.detectors.formatting import FormattingDetector
        formatting_detector = FormattingDetector()
        formatting_result = await formatting_detector.analyze(page_data)
        detector_results.append(formatting_result)
        for breakdown in formatting_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Formatting detector error: {e}")

    # --- Layer 7: Freshness (4%) ---
    try:
        from src.detectors.freshness import FreshnessDetector
        freshness_detector = FreshnessDetector()
        freshness_result = await freshness_detector.analyze(page_data)
        detector_results.append(freshness_result)
        for breakdown in freshness_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Freshness detector error: {e}")

    # --- Layer 9: Links & Verifiability (6%) ---
    try:
        from src.detectors.links import LinksDetector
        links_detector = LinksDetector()
        links_result = await links_detector.analyze(page_data)
        detector_results.append(links_result)
        for breakdown in links_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Links detector error: {e}")

    # --- Layer: Passage Quality (12%) ---
    try:
        from src.detectors.passage_quality import PassageQualityDetector
        passage_detector = PassageQualityDetector()
        passage_result = await passage_detector.analyze(page_data)
        detector_results.append(passage_result)
        for breakdown in passage_result.breakdown:
            all_recommendations.extend(breakdown.recommendations)
    except Exception as e:
        logger.error(f"Passage Quality detector error: {e}")

    # --- Layer: Query Match (10%, optional) ---
    if request.target_query and request.target_query.strip():
        try:
            from src.detectors.query_match import QueryMatchDetector
            query_detector = QueryMatchDetector(target_query=request.target_query.strip())
            query_result = await query_detector.analyze(page_data)
            detector_results.append(query_result)
            for breakdown in query_result.breakdown:
                all_recommendations.extend(breakdown.recommendations)
        except Exception as e:
            logger.error(f"Query match detector error: {e}")

    # Step 3: Calculate total score and normalized contribution
    active_weights_sum = sum(r.weight for r in detector_results)
    if active_weights_sum > 0:
        for r in detector_results:
            r.contribution = (r.score * r.weight) / active_weights_sum
        total_score = sum(r.contribution for r in detector_results)
    else:
        total_score = 0.0

    # Critical bot block check
    has_critical_bot_block = False
    critical_block_reasons = []
    for r in detector_results:
        if r.dimension == "technical_infrastructure" and r.debug_info:
            if r.debug_info.get("has_critical_bot_block"):
                has_critical_bot_block = True
                critical_block_reasons = r.debug_info.get("critical_block_reasons", [])
                break

    score_capped = False
    cap_reason = None

    if has_critical_bot_block:
        score_capped = True
        cap_reason = "; ".join(critical_block_reasons) if critical_block_reasons else "AI search bots or snippet directives blocked"
        total_score = min(30.0, total_score)
        if critical_block_reasons:
            critical_rec = f"CRITICAL: {'; '.join(critical_block_reasons)}"
            if critical_rec not in all_recommendations:
                all_recommendations.insert(0, critical_rec)

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

    analysis_time_ms = (time.time() - start_time) * 1000
    scoring_version = settings.app_version
    top_recommendations = all_recommendations[:5]

    ai_context = None
    if settings.ai_enabled:
        ai_context = _build_ai_context(
            page_data=page_data,
            detector_results=detector_results,
            detected_lang=detected_lang,
            content_type=content_type,
            effective_url=url,
        )

    return AuditResponse(
        url=url,
        total_score=total_score,
        dimensions=dimension_scores,
        scoring_version=scoring_version,
        language=detected_lang,
        content_type=content_type,
        analysis_time_ms=analysis_time_ms,
        analyzed_at=datetime.utcnow(),
        recommendations=top_recommendations,
        score_capped=score_capped,
        cap_reason=cap_reason,
        detector_results=detector_results,
        ai_context=ai_context,
    )


def _build_ai_context(
    page_data: PageData,
    detector_results: list,
    detected_lang: str,
    content_type: str,
    effective_url: str,
) -> AIContext:
    """Extract context elements for optional AI fixes."""
    import json
    import re
    from bs4 import BeautifulSoup
    from src.utils.text_processing import extract_main_content
    from src.detectors.authority import AuthorityDetector
    from src.detectors.freshness import FreshnessDetector

    soup = BeautifulSoup(page_data.html_rendered or page_data.html_raw or "", "lxml")

    # Title & H1
    title = None
    title_el = soup.find("title")
    if title_el and title_el.get_text(strip=True):
        title = title_el.get_text(strip=True)
    elif soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "").strip() or None

    h1 = None
    h1_el = soup.find("h1")
    if h1_el and h1_el.get_text(strip=True):
        h1 = h1_el.get_text(strip=True)

    # Scoped main content
    scoped_html, scoped_text = extract_main_content(page_data.html_rendered or page_data.html_raw)
    main_text = (scoped_text or page_data.text_content or "").strip()
    if len(main_text) > 8000:
        main_text = main_text[:8000]

    # First paragraph (at least 20 words, or first non-empty p)
    first_paragraph = None
    main_soup = BeautifulSoup(scoped_html, "lxml") if scoped_html else soup
    paragraphs = []
    for p in main_soup.find_all("p"):
        pt = p.get_text(separator=" ", strip=True)
        if pt:
            paragraphs.append(pt)

    for pt in paragraphs:
        if len(pt.split()) >= 20:
            first_paragraph = pt
            break
    if not first_paragraph and paragraphs:
        first_paragraph = paragraphs[0]

    # Existing JSON-LD scripts
    existing_json_ld: list[dict] = []
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        try:
            s_text = script.string or script.get_text() or ""
            data = json.loads(s_text)
            if isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    for item in data["@graph"]:
                        if isinstance(item, dict):
                            existing_json_ld.append(item)
                else:
                    existing_json_ld.append(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        existing_json_ld.append(item)
        except Exception:
            continue

    # Truncate existing_json_ld if serialized length exceeds 5000 chars
    try:
        ld_str = json.dumps(existing_json_ld)
        if len(ld_str) > 5000:
            truncated_list = []
            cur_len = 2
            for item in existing_json_ld:
                item_str = json.dumps(item)
                if cur_len + len(item_str) + 2 > 5000:
                    break
                truncated_list.append(item)
                cur_len += len(item_str) + 2
            existing_json_ld = truncated_list
    except Exception:
        pass

    # Author detection
    auth_detector = AuthorityDetector()
    detected_author = (
        auth_detector._extract_author_from_json_ld(page_data.html_rendered) or
        auth_detector._extract_author_from_html(page_data.html_rendered) or
        auth_detector._extract_author_from_text(page_data.text_content, auth_detector.AUTHOR_PATTERNS)
    )

    # Date detection
    freshness_detector = FreshnessDetector()
    date_obj = freshness_detector._extract_date(page_data, lang=detected_lang)
    detected_date_published = date_obj.isoformat() if date_obj else None

    # Check for specific dateModified meta tag
    detected_date_modified = None
    mod_match = re.search(
        r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)["\']',
        page_data.html_rendered or "",
        re.I
    )
    if mod_match:
        detected_date_modified = mod_match.group(1).strip()
    elif detected_date_published:
        detected_date_modified = detected_date_published

    # Publisher detection
    detected_publisher = None
    pub_meta = soup.find("meta", property="og:site_name")
    if pub_meta and pub_meta.get("content"):
        detected_publisher = pub_meta.get("content").strip()
    if not detected_publisher:
        pub_tag = soup.find("meta", attrs={"name": re.compile(r"publisher|site_name", re.I)})
        if pub_tag and pub_tag.get("content"):
            detected_publisher = pub_tag.get("content").strip()
    if not detected_publisher and effective_url and effective_url.startswith(("http://", "https://")):
        detected_publisher = urlparse(effective_url).netloc.replace("www.", "")

    # Failing submetrics (score < 70)
    failing_submetrics: list[FailingSubmetric] = []
    for r in detector_results:
        for b in getattr(r, "breakdown", []):
            if b.raw_score < 70.0:
                rec = b.recommendations[0] if b.recommendations else None
                failing_submetrics.append(
                    FailingSubmetric(
                        name=b.name,
                        score=round(b.raw_score, 1),
                        recommendation=rec,
                    )
                )

    return AIContext(
        url=effective_url if effective_url != "text-mode" else None,
        title=title,
        h1=h1,
        language=detected_lang,
        content_type=content_type,
        main_text=main_text,
        first_paragraph=first_paragraph,
        existing_json_ld=existing_json_ld,
        detected_author=detected_author,
        detected_date_published=detected_date_published,
        detected_date_modified=detected_date_modified,
        detected_publisher=detected_publisher,
        failing_submetrics=failing_submetrics,
    )

