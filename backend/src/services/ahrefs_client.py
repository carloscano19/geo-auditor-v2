"""
GEO-AUDITOR AI - Ahrefs Client
Async client for Ahrefs API v3 to fetch off-page authority and ranking signals.
Never exposes API keys in logs or responses.
"""

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import httpx

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

AHREFS_BASE_URL = "https://api.ahrefs.com/v3"
AHREFS_TIMEOUT = 20.0
AHREFS_CACHE_MAX_SIZE = 200
AHREFS_CACHE_TTL_SECONDS = 7 * 86400  # 7 days

# In-memory cache: normalized_url -> (data_dict, expires_at_timestamp)
ahrefs_cache: OrderedDict[str, Tuple[Dict[str, Any], float]] = OrderedDict()

# Daily usage counter: "YYYY-MM-DD" -> count
ahrefs_daily_usage: Dict[str, int] = {}


def reset_ahrefs_cache() -> None:
    """Clear the in-memory cache for tests."""
    ahrefs_cache.clear()


def reset_ahrefs_daily_usage() -> None:
    """Clear daily usage counters for tests."""
    ahrefs_daily_usage.clear()


def get_ahrefs_daily_count(date_str: Optional[str] = None) -> int:
    """Get current day usage count."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ahrefs_daily_usage.get(date_str, 0)


def increment_ahrefs_daily_count(date_str: Optional[str] = None) -> int:
    """Increment and return current day usage count."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ahrefs_daily_usage[date_str] = ahrefs_daily_usage.get(date_str, 0) + 1
    return ahrefs_daily_usage[date_str]


def normalize_cache_url(url: str) -> str:
    """Normalize URL string for consistent cache keys."""
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        u = f"https://{u}"
    parsed = urlparse(u)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
    return f"{parsed.scheme}://{netloc}{path}"


def get_cached_ahrefs_data(url: str) -> Optional[Dict[str, Any]]:
    """Retrieve unexpired cached Ahrefs metrics if available."""
    key = normalize_cache_url(url)
    now_ts = datetime.now(timezone.utc).timestamp()
    if key in ahrefs_cache:
        data, expires_at = ahrefs_cache[key]
        if now_ts < expires_at:
            # Move to end (LRU)
            ahrefs_cache.move_to_end(key)
            return dict(data)
        else:
            ahrefs_cache.pop(key, None)
    return None


def put_cached_ahrefs_data(url: str, data: Dict[str, Any]) -> None:
    """Store Ahrefs metrics in cache with 7-day TTL and LRU eviction."""
    key = normalize_cache_url(url)
    now_ts = datetime.now(timezone.utc).timestamp()
    expires_at = now_ts + AHREFS_CACHE_TTL_SECONDS

    # Evict expired entries
    expired_keys = [k for k, (_, exp) in ahrefs_cache.items() if exp <= now_ts]
    for k in expired_keys:
        ahrefs_cache.pop(k, None)

    if key in ahrefs_cache:
        ahrefs_cache.pop(key, None)

    ahrefs_cache[key] = (data, expires_at)

    while len(ahrefs_cache) > AHREFS_CACHE_MAX_SIZE:
        ahrefs_cache.popitem(last=False)


def extract_domain_from_url(url: str) -> str:
    """Extract domain from URL, stripping protocol, port, and www."""
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        u = f"https://{u}"
    try:
        parsed = urlparse(u)
        netloc = (parsed.netloc or parsed.path).split(":")[0].strip().lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return url


class AhrefsClient:
    """Async client for Ahrefs API v3 with retries on 5xx and error sanitization."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or "").strip()

    async def _get_endpoint(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Execute single GET request to Ahrefs with 1 retry on 5xx.
        Returns parsed JSON dict or None on any failure.
        """
        url = f"{AHREFS_BASE_URL}{endpoint}"
        for attempt in range(2):
            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=AHREFS_TIMEOUT,
                )
                if resp.status_code >= 500:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    logger.warning("Ahrefs 5xx error on endpoint %s (status %d)", endpoint, resp.status_code)
                    return None
                if resp.is_success:
                    return resp.json()
                logger.warning("Ahrefs request to %s returned status %d", endpoint, resp.status_code)
                return None
            except httpx.HTTPError as exc:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                logger.warning("Ahrefs HTTP error on endpoint %s: %s", endpoint, type(exc).__name__)
                return None
            except Exception as exc:
                logger.warning("Unexpected error calling Ahrefs endpoint %s: %s", endpoint, type(exc).__name__)
                return None
        return None

    async def fetch_offpage_signals(self, url: str) -> Dict[str, Any]:
        """
        Fetch off-page signals for a URL using 4 parallel GET requests:
        1. /site-explorer/backlinks-stats?target=<url>&mode=exact&date=...
        2. /site-explorer/metrics?target=<url>&mode=exact&date=...
        3. /site-explorer/domain-rating?target=<dominio>&date=...
        4. /site-explorer/url-rating-history?target=<url>&date_from=<hoy-30d>&history_grouping=monthly

        If any single request fails, its fields are returned as None/null without failing the rest.
        """
        if not self.api_key:
            raise ValueError("Ahrefs API key is not configured")

        today_dt = datetime.now(timezone.utc).date()
        today_str = today_dt.strftime("%Y-%m-%d")
        thirty_days_ago_str = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        domain = extract_domain_from_url(url)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            req_backlinks = self._get_endpoint(
                client,
                "/site-explorer/backlinks-stats",
                {"target": url, "mode": "exact", "date": today_str},
                headers,
            )
            req_metrics = self._get_endpoint(
                client,
                "/site-explorer/metrics",
                {"target": url, "mode": "exact", "date": today_str},
                headers,
            )
            req_dr = self._get_endpoint(
                client,
                "/site-explorer/domain-rating",
                {"target": domain, "date": today_str},
                headers,
            )
            req_ur_hist = self._get_endpoint(
                client,
                "/site-explorer/url-rating-history",
                {"target": url, "date_from": thirty_days_ago_str, "history_grouping": "monthly"},
                headers,
            )

            res_backlinks, res_metrics, res_dr, res_ur_hist = await asyncio.gather(
                req_backlinks, req_metrics, req_dr, req_ur_hist, return_exceptions=True
            )

        # 1. Parse backlinks-stats
        backlinks: Optional[int] = None
        referring_domains: Optional[int] = None
        referring_domains_all_time: Optional[int] = None

        if isinstance(res_backlinks, dict):
            m = res_backlinks.get("metrics") or {}
            if isinstance(m, dict):
                if "live" in m and m["live"] is not None:
                    try:
                        backlinks = int(m["live"])
                    except (ValueError, TypeError):
                        pass
                if "live_refdomains" in m and m["live_refdomains"] is not None:
                    try:
                        referring_domains = int(m["live_refdomains"])
                    except (ValueError, TypeError):
                        pass
                if "all_time_refdomains" in m and m["all_time_refdomains"] is not None:
                    try:
                        referring_domains_all_time = int(m["all_time_refdomains"])
                    except (ValueError, TypeError):
                        pass

        # 2. Parse metrics
        organic_keywords: Optional[int] = None
        top3_keywords: Optional[int] = None
        organic_traffic: Optional[float] = None

        if isinstance(res_metrics, dict):
            m = res_metrics.get("metrics") or {}
            if isinstance(m, dict):
                if "org_keywords" in m and m["org_keywords"] is not None:
                    try:
                        organic_keywords = int(m["org_keywords"])
                    except (ValueError, TypeError):
                        pass
                if "org_keywords_1_3" in m and m["org_keywords_1_3"] is not None:
                    try:
                        top3_keywords = int(m["org_keywords_1_3"])
                    except (ValueError, TypeError):
                        pass
                if "org_traffic" in m and m["org_traffic"] is not None:
                    try:
                        organic_traffic = float(m["org_traffic"])
                    except (ValueError, TypeError):
                        pass

        # 3. Parse domain-rating
        domain_rating: Optional[float] = None
        if isinstance(res_dr, dict):
            dr_obj = res_dr.get("domain_rating")
            if isinstance(dr_obj, dict):
                val = dr_obj.get("domain_rating")
                if val is not None:
                    try:
                        domain_rating = float(val)
                    except (ValueError, TypeError):
                        pass
            elif isinstance(dr_obj, (int, float)):
                domain_rating = float(dr_obj)

        # 4. Parse url-rating-history (most recent url_rating)
        url_rating: Optional[float] = None
        if isinstance(res_ur_hist, dict):
            ratings_list = res_ur_hist.get("url_ratings")
            if isinstance(ratings_list, list) and ratings_list:
                valid_points = [
                    r for r in ratings_list
                    if isinstance(r, dict) and r.get("url_rating") is not None
                ]
                if valid_points:
                    # Sort by date descending to get the most recent point
                    sorted_pts = sorted(
                        valid_points,
                        key=lambda x: str(x.get("date", "")),
                        reverse=True,
                    )
                    try:
                        url_rating = float(sorted_pts[0]["url_rating"])
                    except (ValueError, TypeError, KeyError):
                        pass

        return {
            "domain_rating": domain_rating,
            "url_rating": url_rating,
            "referring_domains": referring_domains,
            "backlinks": backlinks,
            "referring_domains_all_time": referring_domains_all_time,
            "organic_keywords": organic_keywords,
            "top3_keywords": top3_keywords,
            "organic_traffic": organic_traffic,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
