"""
GEO-AUDITOR AI - DataForSEO Live SERP Client

Integrates Google Search live SERP data (People Also Ask, AI Overview sources,
organic top 10 results, and related searches) via DataForSEO.
Includes in-memory 24h caching and domain/social exclusions.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from config.settings import Settings, get_settings
from src.detectors.links import LinksDetector

logger = logging.getLogger(__name__)

# Social domains to filter from citation sources
SOCIAL_DOMAINS = LinksDetector.SOCIAL_DOMAINS

SERP_CACHE_MAX_ENTRIES = 100
# Cache mapping: key -> (parsed_data, expires_at_timestamp)
serp_cache: dict[str, tuple[dict, float]] = {}


class SerpClientError(Exception):
    """Base exception for DataForSEO SERP client errors with sanitized messages."""
    pass


class SerpDailyLimitExceededError(SerpClientError):
    """Raised when the daily DataForSEO call limit is exceeded."""
    pass


class SerpDailyCallTracker:
    """In-memory daily call counter resetting at UTC midnight for DataForSEO."""

    def __init__(self):
        self._current_date_utc = datetime.now(timezone.utc).date()
        self._call_count = 0

    def _reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self._current_date_utc:
            self._current_date_utc = today
            self._call_count = 0

    def get_count(self) -> int:
        self._reset_if_new_day()
        return self._call_count

    def check_and_increment(self, max_limit: int) -> int:
        self._reset_if_new_day()
        if self._call_count >= max_limit:
            raise SerpDailyLimitExceededError("Daily Google data limit reached, try again tomorrow")
        self._call_count += 1
        return self._call_count

    def reset_for_tests(self):
        self._current_date_utc = datetime.now(timezone.utc).date()
        self._call_count = 0


serp_daily_tracker = SerpDailyCallTracker()


def get_market_for_language(lang: str) -> tuple[int, str, str]:
    """
    Returns (location_code, language_code, market_display).
    - 'es' -> 2724, 'es', 'ES/es'
    - 'en' / others -> 2840, 'en', 'US/en'
    """
    if lang and lang.lower().startswith("es"):
        return 2724, "es", "ES/es"
    return 2840, "en", "US/en"


def normalize_domain(domain_or_url: str) -> str:
    """Normalize a domain or URL by lowercasing and removing 'www.'."""
    if not domain_or_url:
        return ""
    val = domain_or_url.strip()
    if val.startswith("http://") or val.startswith("https://"):
        try:
            return urlparse(val).netloc.lower().replace("www.", "")
        except Exception:
            return ""
    # Strip paths if any
    clean = val.split("/")[0].lower()
    return clean.replace("www.", "")


def is_excluded_domain(domain: str, url: str, page_domain: str) -> bool:
    """
    Check if a domain or URL belongs to the audited page or a blocked social network.
    """
    dom = normalize_domain(domain or url)
    if not dom:
        return True
    
    # Check against audited page domain
    if page_domain:
        norm_page_dom = normalize_domain(page_domain)
        if dom == norm_page_dom or dom.endswith("." + norm_page_dom):
            return True

    # Check against social networks
    for social in SOCIAL_DOMAINS:
        if social in dom:
            return True

    return False


def get_serp_cache_entry(key: str) -> Optional[dict]:
    """Retrieve entry from in-memory SERP cache if not expired."""
    now_ts = datetime.now(timezone.utc).timestamp()
    if key in serp_cache:
        data, exp = serp_cache[key]
        if now_ts < exp:
            return data
        serp_cache.pop(key, None)
    return None


def put_serp_cache_entry(key: str, data: dict, exp: float):
    """Store entry in SERP cache with 24h TTL and max 100 entries eviction."""
    now_ts = datetime.now(timezone.utc).timestamp()
    # Clean up expired
    expired = [k for k, (_, e) in serp_cache.items() if now_ts >= e]
    for k in expired:
        serp_cache.pop(k, None)
    # Evict oldest if full
    while len(serp_cache) >= SERP_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(serp_cache))
        serp_cache.pop(oldest_key, None)
    serp_cache[key] = (data, exp)


class SerpClient:
    """DataForSEO Google Live SERP client."""

    API_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    async def fetch_serp_live(
        self,
        query: str,
        language: str = "en",
        audited_url: str = "",
    ) -> dict:
        """
        Fetch SERP data for query and parse PAA, AI Overview sources, organic top 10,
        and related searches.
        """
        if not self.settings.serp_enabled:
            raise SerpClientError("DataForSEO is not configured or disabled.")

        clean_query = query.strip()
        if not clean_query:
            raise SerpClientError("Search query cannot be empty.")

        location_code, language_code, market_display = get_market_for_language(language)
        cache_key = f"{clean_query.lower()}::{market_display}"

        cached = get_serp_cache_entry(cache_key)
        if cached is not None:
            return cached

        # Check and increment daily limit for external DataForSEO calls
        serp_daily_tracker.check_and_increment(self.settings.serp_daily_limit)

        payload = [
            {
                "keyword": clean_query,
                "location_code": location_code,
                "language_code": language_code,
                "depth": 10,
                "load_async_ai_overview": True,
            }
        ]

        auth = httpx.BasicAuth(
            self.settings.dataforseo_login,
            self.settings.dataforseo_password,
        )

        data = None
        timeout = httpx.Timeout(30.0)

        # Execute with 1 retry on 5xx
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(2):
                try:
                    resp = await client.post(
                        self.API_URL,
                        auth=auth,
                        json=payload,
                    )
                    if resp.status_code >= 500 and attempt == 0:
                        await asyncio.sleep(1.0)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code >= 500 and attempt == 0:
                        await asyncio.sleep(1.0)
                        continue
                    raise SerpClientError(
                        f"DataForSEO request failed with HTTP status {e.response.status_code}"
                    )
                except httpx.RequestError as e:
                    if attempt == 0:
                        await asyncio.sleep(1.0)
                        continue
                    raise SerpClientError("DataForSEO connection timeout or network error")
                except Exception as e:
                    raise SerpClientError("Failed to communicate with DataForSEO")

        if not data or not isinstance(data, dict):
            raise SerpClientError("Empty or invalid response from DataForSEO")

        tasks = data.get("tasks", [])
        if not tasks or not isinstance(tasks, list):
            raise SerpClientError("No tasks returned by DataForSEO")

        task = tasks[0]
        task_status = task.get("status_code")
        if task_status is not None and task_status != 20000 and task_status != 200:
            msg = task.get("status_message", "Task error")
            raise SerpClientError(f"DataForSEO error: {msg}")

        results = task.get("result", [])
        items = []
        if results and isinstance(results, list):
            items = results[0].get("items", []) or []

        parsed = self._parse_items(items, audited_url, clean_query, market_display)

        # Store in 24h cache (86400 seconds)
        now_ts = datetime.now(timezone.utc).timestamp()
        put_serp_cache_entry(cache_key, parsed, now_ts + 86400)

        return parsed

    def _parse_items(
        self,
        items: list,
        audited_url: str,
        query: str,
        market_display: str,
    ) -> dict:
        """Parse raw DataForSEO SERP items and filter exclusions."""
        page_domain = normalize_domain(audited_url)

        people_also_ask: list[dict] = []
        ai_overview_sources: list[dict] = []
        organic: list[dict] = []
        related_searches: list[str] = []

        def _extract_paa_item(entry: dict) -> Optional[dict]:
            q_text = (entry.get("title") or entry.get("question") or entry.get("seed_question") or "").strip()
            if not q_text:
                return None
            
            exp = entry.get("expanded_element")
            exp_url = ""
            exp_dom = ""
            if isinstance(exp, list) and exp and isinstance(exp[0], dict):
                exp_url = (exp[0].get("url") or exp[0].get("link") or "").strip()
                exp_dom = (exp[0].get("domain") or "").strip()

            url = exp_url or (entry.get("url") or entry.get("link") or "").strip()
            dom = exp_dom or (entry.get("domain") or "").strip()
            if not dom and url:
                dom = normalize_domain(url)
            if is_excluded_domain(dom, url, page_domain):
                url = ""
                dom = ""
            return {
                "question": q_text,
                "url": url or None,
                "domain": dom or None,
            }

        for item in items:
            if not isinstance(item, dict):
                continue
            itype = item.get("type")

            # 1. People Also Ask (only people_also_ask and people_also_ask_element)
            if itype == "people_also_ask":
                sub_items = item.get("items") or []
                for sub in sub_items:
                    if isinstance(sub, dict):
                        paa = _extract_paa_item(sub)
                        if paa:
                            people_also_ask.append(paa)
            elif itype == "people_also_ask_element":
                paa = _extract_paa_item(item)
                if paa:
                    people_also_ask.append(paa)

            # 2. People Also Search (not questions; add titles to related_searches without duplicates)
            elif itype in ["people_also_search", "people_also_search_element"]:
                sub_items = item.get("items") or []
                for s in sub_items:
                    if isinstance(s, str) and s.strip():
                        t = s.strip()
                        if t not in related_searches:
                            related_searches.append(t)
                    elif isinstance(s, dict):
                        t = (s.get("title") or s.get("query") or s.get("keyword") or "").strip()
                        if t and t not in related_searches:
                            related_searches.append(t)
                if not sub_items:
                    t = (item.get("title") or item.get("query") or "").strip()
                    if t and t not in related_searches:
                        related_searches.append(t)

            # 3. AI Overview
            elif itype == "ai_overview":
                refs = item.get("references") or item.get("sources") or item.get("items") or []
                for ref in refs:
                    if isinstance(ref, dict):
                        url = (ref.get("url") or ref.get("link") or "").strip()
                        title = (ref.get("title") or ref.get("name") or "").strip()
                        dom = (ref.get("domain") or "").strip()
                        if not dom and url:
                            dom = normalize_domain(url)
                        if url and dom and not is_excluded_domain(dom, url, page_domain):
                            ai_overview_sources.append({
                                "url": url,
                                "title": title or dom,
                                "domain": dom,
                            })

            # 4. Organic top 10
            elif itype == "organic":
                url = (item.get("url") or item.get("link") or "").strip()
                title = (item.get("title") or "").strip()
                dom = (item.get("domain") or "").strip()
                if not dom and url:
                    dom = normalize_domain(url)
                if url and dom and not is_excluded_domain(dom, url, page_domain):
                    organic.append({
                        "url": url,
                        "title": title or dom,
                        "domain": dom,
                    })

            # 5. Related Searches
            elif itype in ["related_searches", "related_search"]:
                sub_items = item.get("items") or []
                for s in sub_items:
                    if isinstance(s, str) and s.strip():
                        t = s.strip()
                        if t not in related_searches:
                            related_searches.append(t)
                    elif isinstance(s, dict):
                        qt = (s.get("query") or s.get("title") or s.get("keyword") or "").strip()
                        if qt and qt not in related_searches:
                            related_searches.append(qt)

        # Slice organic to top 10
        organic = organic[:10]

        return {
            "query": query,
            "market": market_display,
            "people_also_ask": people_also_ask,
            "ai_overview_sources": ai_overview_sources,
            "organic": organic,
            "related_searches": related_searches,
        }
