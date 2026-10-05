import pytest
import io
import docx
import httpx
from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app, reset_failed_auth_attempts
from config.settings import Settings, get_settings
from src.services.ahrefs_client import (
    AhrefsClient,
    reset_ahrefs_cache,
    reset_ahrefs_daily_usage,
    get_ahrefs_daily_count,
)
from src.utils.lang_patterns import generate_ahrefs_recommendations
from src.utils.docx_brief import (
    generate_editor_brief_docx,
    get_top_non_technical_actions,
)
from src.models.schemas import (
    AuditResponse,
    DetectorResult,
    ScoreBreakdown,
    AhrefsOffpageResponse,
)


@pytest.fixture(autouse=True)
def reset_all_state():
    reset_failed_auth_attempts()
    reset_ahrefs_cache()
    reset_ahrefs_daily_usage()
    get_settings.cache_clear()
    yield
    reset_failed_auth_attempts()
    reset_ahrefs_cache()
    reset_ahrefs_daily_usage()
    get_settings.cache_clear()


def make_test_audit_response() -> AuditResponse:
    det = DetectorResult(
        dimension="content_richness",
        score=75.0,
        weight=0.10,
        contribution=7.5,
        breakdown=[
            ScoreBreakdown(
                name="Content Depth",
                raw_score=40.0,
                weight=1.0,
                weighted_score=40.0,
                explanation="Content could be deeper.",
                recommendations=["Add detailed case studies."],
            )
        ],
    )
    return AuditResponse(
        url="https://example.com/test-article",
        total_score=75.0,
        dimensions=[],
        scoring_version="v2.0",
        analysis_time_ms=120.0,
        recommendations=["Improve depth"],
        detector_results=[det],
    )


# 1. Config and /api/version tests
def test_ahrefs_enabled_configuration():
    s_disabled = Settings(ahrefs_api_key="", access_code="")
    assert s_disabled.ahrefs_enabled is False

    s_enabled = Settings(ahrefs_api_key="test-ahrefs-key", access_code="")
    assert s_enabled.ahrefs_enabled is True

    # Check repr does not expose key
    assert "test-ahrefs-key" not in repr(s_enabled)


def test_api_version_returns_ahrefs_enabled():
    client = TestClient(app)

    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ahrefs_api_key="", access_code="")
        res = client.get("/api/version")
        assert res.status_code == 200
        assert res.json()["ahrefs_enabled"] is False

    get_settings.cache_clear()
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ahrefs_api_key="ahrefs-active-key", access_code="")
        res = client.get("/api/version")
        assert res.status_code == 200
        assert res.json()["ahrefs_enabled"] is True


# 2. Endpoint /api/offpage auth and status tests
def test_offpage_endpoint_503_when_disabled():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ahrefs_api_key="", access_code="")
        res = client.post("/api/offpage", json={"url": "https://example.com/page"})
        assert res.status_code == 503
        assert "Ahrefs is not configured" in res.json()["detail"]


def test_offpage_endpoint_401_with_access_code():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="test-key",
            access_code="secret-code-123"
        )
        # Without header
        res_no_auth = client.post("/api/offpage", json={"url": "https://example.com/page"})
        assert res_no_auth.status_code == 401

        # With wrong header
        res_wrong_auth = client.post(
            "/api/offpage",
            json={"url": "https://example.com/page"},
            headers={"X-Access-Code": "wrong"}
        )
        assert res_wrong_auth.status_code == 401


def test_offpage_endpoint_429_when_daily_limit_exceeded():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="test-key",
            ahrefs_daily_limit=2,
            access_code=""
        )

        with patch("src.services.ahrefs_client.AhrefsClient.fetch_offpage_signals") as mock_fetch:
            mock_fetch.return_value = {
                "domain_rating": 50.0,
                "url_rating": 10.0,
                "referring_domains": 5,
                "backlinks": 20,
                "referring_domains_all_time": 25,
                "organic_keywords": 10,
                "top3_keywords": 1,
                "organic_traffic": 100.0,
                "checked_at": "2026-10-02T12:00:00Z",
            }

            # 1st call (counts as 1)
            res1 = client.post("/api/offpage", json={"url": "https://example.com/page-1"})
            assert res1.status_code == 200

            # 2nd call (counts as 2)
            res2 = client.post("/api/offpage", json={"url": "https://example.com/page-2"})
            assert res2.status_code == 200

            # 3rd call: limit is 2 -> should 429
            res3 = client.post("/api/offpage", json={"url": "https://example.com/page-3"})
            assert res3.status_code == 429
            assert "Daily Ahrefs limit reached" in res3.json()["detail"]


def test_offpage_endpoint_503_on_ahrefs_auth_error():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="invalid-ahrefs-key",
            access_code=""
        )

        with patch("src.services.ahrefs_client.AhrefsClient._get_endpoint") as mock_get:
            from src.services.ahrefs_client import AhrefsAuthError
            mock_get.side_effect = AhrefsAuthError("Ahrefs rejected the API key")

            res = client.post("/api/offpage", json={"url": "https://example.com/test-auth"})
            assert res.status_code == 503
            assert res.json()["detail"] == "Ahrefs rejected the API key. Check GEO_AUDITOR_AHREFS_API_KEY."
            assert "invalid-ahrefs-key" not in res.text

            # Ensure nothing was cached and daily counter was not incremented
            assert get_ahrefs_daily_count() == 0
            from src.services.ahrefs_client import get_cached_ahrefs_data
            assert get_cached_ahrefs_data("https://example.com/test-auth") is None


def test_offpage_endpoint_502_when_all_requests_fail():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="test-key",
            access_code=""
        )

        with patch("src.services.ahrefs_client.AhrefsClient._get_endpoint") as mock_get:
            # All 4 return None (e.g. 500 status codes from Ahrefs)
            mock_get.return_value = None

            res = client.post("/api/offpage", json={"url": "https://example.com/test-fail"})
            assert res.status_code == 502
            assert res.json()["detail"] == "Ahrefs returned no data. Try again later."

            # Ensure nothing was cached and daily counter was not incremented
            assert get_ahrefs_daily_count() == 0
            from src.services.ahrefs_client import get_cached_ahrefs_data
            assert get_cached_ahrefs_data("https://example.com/test-fail") is None


def test_offpage_endpoint_partial_response_cached_and_counted():
    client = TestClient(app)
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="test-key",
            access_code=""
        )

        async def mock_endpoint(cl, endpoint, params, headers):
            if "domain-rating" in endpoint:
                return {"domain_rating": {"domain_rating": 60.0}}
            # Other 3 endpoints fail (return None)
            return None

        with patch("src.services.ahrefs_client.AhrefsClient._get_endpoint", side_effect=mock_endpoint):
            res = client.post("/api/offpage", json={"url": "https://example.com/test-partial"})
            assert res.status_code == 200
            data = res.json()
            assert data["domain_rating"] == 60.0
            assert data["backlinks"] is None

            # Cached and daily counter incremented
            assert get_ahrefs_daily_count() == 1
            from src.services.ahrefs_client import get_cached_ahrefs_data
            cached = get_cached_ahrefs_data("https://example.com/test-partial")
            assert cached is not None
            assert cached["domain_rating"] == 60.0


# 3. Parsing of 4 responses and partial failure handling
@pytest.mark.asyncio
async def test_ahrefs_client_parsing_and_most_recent_url_rating():
    client = AhrefsClient(api_key="test-key")

    async def mock_endpoint(cl, endpoint, params, headers):
        if "backlinks-stats" in endpoint:
            return {
                "metrics": {
                    "live": 1500,
                    "live_refdomains": 42,
                    "all_time_refdomains": 75,
                }
            }
        elif "metrics" in endpoint:
            return {
                "metrics": {
                    "org_keywords": 280,
                    "org_keywords_1_3": 14,
                    "org_traffic": 1850.5,
                }
            }
        elif "domain-rating" in endpoint:
            return {
                "domain_rating": {
                    "domain_rating": 64.0
                }
            }
        elif "url-rating-history" in endpoint:
            return {
                "url_ratings": [
                    {"date": "2026-09-01", "url_rating": 12.0},
                    {"date": "2026-10-01", "url_rating": 22.5},
                    {"date": "2026-09-15", "url_rating": 18.0},
                ]
            }
        return None

    with patch.object(client, "_get_endpoint", side_effect=mock_endpoint):
        res = await client.fetch_offpage_signals("https://example.com/blog/article")

        assert res["backlinks"] == 1500
        assert res["referring_domains"] == 42
        assert res["referring_domains_all_time"] == 75
        assert res["organic_keywords"] == 280
        assert res["top3_keywords"] == 14
        assert res["organic_traffic"] == 1850.5
        assert res["domain_rating"] == 64.0
        # Check most recent point by date: 2026-10-01 -> 22.5
        assert res["url_rating"] == 22.5


@pytest.mark.asyncio
async def test_ahrefs_client_partial_failure_returns_null_and_rest():
    client = AhrefsClient(api_key="test-key")

    async def mock_endpoint(cl, endpoint, params, headers):
        if "backlinks-stats" in endpoint:
            return {"metrics": {"live": 250, "live_refdomains": 12, "all_time_refdomains": 18}}
        elif "metrics" in endpoint:
            # Fails: returns None
            return None
        elif "domain-rating" in endpoint:
            return {"domain_rating": {"domain_rating": 55.0}}
        elif "url-rating-history" in endpoint:
            # Fails: returns None
            return None
        return None

    with patch.object(client, "_get_endpoint", side_effect=mock_endpoint):
        res = await client.fetch_offpage_signals("https://example.com/page")

        # backlinks and DR succeeded
        assert res["backlinks"] == 250
        assert res["referring_domains"] == 12
        assert res["domain_rating"] == 55.0

        # metrics and UR failed -> None
        assert res["organic_keywords"] is None
        assert res["top3_keywords"] is None
        assert res["organic_traffic"] is None
        assert res["url_rating"] is None


# 4. Recommendation rules and edge cases
def test_recommendation_rules():
    # Case A: referring_domains == 0
    recs = generate_ahrefs_recommendations(referring_domains=0, language="en")
    assert any("No other website links to this page" in r for r in recs)

    # Case B: referring_domains == 1 (1 to 4)
    recs_1 = generate_ahrefs_recommendations(referring_domains=1, language="en")
    assert any("Only 1 website links to this page" in r for r in recs_1)

    # Case C: referring_domains == 4 (1 to 4)
    recs_4 = generate_ahrefs_recommendations(referring_domains=4, language="en")
    assert any("Only 4 websites link to this page" in r for r in recs_4)

    # Case D: referring_domains == 5 (no recommendation triggered)
    recs_5 = generate_ahrefs_recommendations(referring_domains=5, language="en")
    assert not any("website" in r for r in recs_5)

    # Case E: organic_keywords == 0
    recs_kw0 = generate_ahrefs_recommendations(organic_keywords=0, language="en")
    assert any("This page doesn't rank in Google's top 100" in r for r in recs_kw0)

    # Case F: organic_keywords > 0 and top3_keywords == 0
    recs_kw_notop3 = generate_ahrefs_recommendations(organic_keywords=18, top3_keywords=0, language="en")
    assert any("The page ranks for 18 keywords but none in the top 3" in r for r in recs_kw_notop3)

    # Case G: organic_keywords > 0 and top3_keywords > 0 (no recommendation triggered)
    recs_kw_top3 = generate_ahrefs_recommendations(organic_keywords=18, top3_keywords=2, language="en")
    assert not any("keywords but none in the top 3" in r for r in recs_kw_top3)

    # Case H: url_rating < 10 and domain_rating >= 50
    recs_ur = generate_ahrefs_recommendations(url_rating=7.0, domain_rating=62.0, language="en")
    assert any("The domain is strong (DR 62) but this page has little authority of its own (UR 7)" in r for r in recs_ur)

    # Case I: url_rating >= 10 or domain_rating < 50 (no recommendation triggered)
    recs_ur_high = generate_ahrefs_recommendations(url_rating=15.0, domain_rating=62.0, language="en")
    assert not any("little authority of its own" in r for r in recs_ur_high)

    recs_dr_low = generate_ahrefs_recommendations(url_rating=7.0, domain_rating=45.0, language="en")
    assert not any("little authority of its own" in r for r in recs_dr_low)

    # Case J: Missing data (None) -> rule not applied
    recs_none = generate_ahrefs_recommendations(
        referring_domains=None,
        organic_keywords=None,
        top3_keywords=None,
        url_rating=None,
        domain_rating=None,
    )
    assert recs_none == []


def test_recommendation_rules_spanish():
    recs_es = generate_ahrefs_recommendations(
        referring_domains=0,
        organic_keywords=0,
        url_rating=6.0,
        domain_rating=55.0,
        language="es"
    )
    assert any("Ningún otro sitio web enlaza a esta página" in r for r in recs_es)
    assert any("Esta página no posiciona en el top 100 de Google" in r for r in recs_es)
    assert any("El dominio es fuerte (DR 55) pero esta página tiene poca autoridad propia (UR 6)" in r for r in recs_es)


# 5. Cache test: 2 calls to same URL = 4 calls to Ahrefs, not 8
def test_ahrefs_cache_avoids_duplicate_api_calls():
    client = TestClient(app)

    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ahrefs_api_key="test-key",
            access_code=""
        )

        with patch("src.services.ahrefs_client.AhrefsClient.fetch_offpage_signals") as mock_fetch:
            mock_fetch.return_value = {
                "domain_rating": 70.0,
                "url_rating": 15.0,
                "referring_domains": 10,
                "backlinks": 100,
                "referring_domains_all_time": 120,
                "organic_keywords": 50,
                "top3_keywords": 5,
                "organic_traffic": 500.0,
                "checked_at": "2026-10-02T12:00:00Z",
            }

            # First call for URL -> should call fetch_offpage_signals (which does 4 requests)
            res1 = client.post("/api/offpage", json={"url": "https://example.com/cached-test"})
            assert res1.status_code == 200
            assert mock_fetch.call_count == 1
            assert get_ahrefs_daily_count() == 1

            # Second call for SAME URL -> should be cached, no additional fetch
            res2 = client.post("/api/offpage", json={"url": "https://example.com/cached-test"})
            assert res2.status_code == 200
            assert mock_fetch.call_count == 1  # Still 1 (4 requests total, not 8)
            assert get_ahrefs_daily_count() == 1  # Daily quota not decremented again


# 6. Word docx includes Ahrefs section when provided
def test_docx_includes_ahrefs_section_when_provided():
    audit_res = make_test_audit_response()
    ahrefs_data = AhrefsOffpageResponse(
        domain_rating=72.0,
        url_rating=25.0,
        referring_domains=150,
        backlinks=3200,
        referring_domains_all_time=3800,
        organic_keywords=450,
        top3_keywords=28,
        organic_traffic=12500.0,
        checked_at="2026-10-02T12:00:00Z",
        recommendations=["Strengthen the content for its main query to get cited."],
    )

    docx_bytes = generate_editor_brief_docx(
        audit_result=audit_res,
        ahrefs_offpage=ahrefs_data,
    )
    doc = docx.Document(io.BytesIO(docx_bytes))

    doc_text = " ".join([p.text for p in doc.paragraphs])
    assert "Off-page signals (Ahrefs)" in doc_text
    assert "Data from Ahrefs. Not included in the Citation Score." in doc_text
    assert "Off-page recommendations:" in doc_text
    assert "Strengthen the content for its main query to get cited." in doc_text

    # Check table contents
    table_texts = [cell.text for t in doc.tables for row in t.rows for cell in row.cells]
    assert "Domain Rating" in table_texts
    assert "72" in table_texts
    assert "Backlinks" in table_texts
    assert "3,200" in table_texts


def test_docx_omits_ahrefs_section_when_none():
    audit_res = make_test_audit_response()
    docx_bytes = generate_editor_brief_docx(
        audit_result=audit_res,
        ahrefs_offpage=None,
    )
    doc = docx.Document(io.BytesIO(docx_bytes))
    doc_text = " ".join([p.text for p in doc.paragraphs])
    assert "Off-page signals (Ahrefs)" not in doc_text


# 7. PARTE D: Top actions filter in .docx
def test_top_actions_filters_by_score_and_recommendation():
    """
    Submetrics:
    - Score 85 with no recommendation: excluded (>= 70 and no rec)
    - Score 40 with recommendation: included (< 70 and has rec)
    - Score 50 with no recommendation: excluded (< 70 but no rec; explanation never used)
    """
    det = DetectorResult(
        dimension="content_richness",
        score=58.3,
        weight=0.10,
        contribution=5.8,
        breakdown=[
            ScoreBreakdown(
                name="Content Depth",
                raw_score=85.0,
                weight=0.33,
                weighted_score=28.0,
                explanation="Good depth.",
                recommendations=[],  # No rec, score 85 -> excluded
            ),
            ScoreBreakdown(
                name="Statistics Presence",
                raw_score=40.0,
                weight=0.33,
                weighted_score=13.2,
                explanation="Few statistics.",
                recommendations=["Include specific statistics and research data."],  # Included
            ),
            ScoreBreakdown(
                name="Key Takeaways",
                raw_score=50.0,
                weight=0.34,
                weighted_score=17.0,
                explanation="No takeaways summary.",
                recommendations=[],  # No rec, score 50 -> excluded (never use explanation)
            ),
        ],
    )

    actions = get_top_non_technical_actions([det])
    names = [a[0] for a in actions]

    assert len(actions) == 1
    assert names[0] == "Statistics Presence"
    assert actions[0][1] == "Include specific statistics and research data."
    assert "Content Depth" not in names
    assert "Key Takeaways" not in names


# 8. Citation Score invariance with and without Ahrefs
def test_citation_score_invariance_with_and_without_ahrefs():
    """
    Ensures that Citation Score is strictly computed on-page and identical
    regardless of Ahrefs status.
    """
    client = TestClient(app)
    synthetic_content = """
    # Understanding Renewable Energy Systems

    Renewable energy accounted for 29% of global electricity generation according to the International Energy Agency.
    In this comprehensive guide, we examine power production trends across continents.

    ## Solar and Wind Generation
    Solar energy expanded by 22% while wind energy grew by 15% across major industrialized economies during 2025.
    Both technologies represent fundamental pillars of modern electrical infrastructure.

    ## Key Implementation Criteria
    1. Grid integration and storage efficiency.
    2. Decentralized generation near industrial clusters.
    3. Long-term power purchase agreements.
    """

    # 1. Audit without Ahrefs
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ahrefs_api_key="", access_code="")
        res_without = client.post("/api/audit", json={"content_text": synthetic_content})
        assert res_without.status_code == 200
        data_without = res_without.json()

    # 2. Audit with Ahrefs enabled
    get_settings.cache_clear()
    with patch("main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ahrefs_api_key="ahrefs-secret-key", access_code="")
        res_with = client.post("/api/audit", json={"content_text": synthetic_content})
        assert res_with.status_code == 200
        data_with = res_with.json()

    assert data_without["total_score"] == data_with["total_score"]
    assert len(data_without["dimensions"]) == len(data_with["dimensions"])
    for d1, d2 in zip(data_without["dimensions"], data_with["dimensions"]):
        assert d1["score"] == d2["score"]
        assert d1["name"] == d2["name"]


# 9. Linking pages ("Who links to this page") tests
@pytest.mark.asyncio
async def test_ahrefs_client_parses_all_backlinks_linking_pages():
    client = AhrefsClient(api_key="test-key")

    async def mock_endpoint(cl, endpoint, params, headers):
        if "backlinks-stats" in endpoint:
            return {"metrics": {"live": 10, "live_refdomains": 5, "all_time_refdomains": 10}}
        elif "all-backlinks" in endpoint:
            return {
                "backlinks": [
                    {
                        "url_from": "https://authoritative.org/guide",
                        "name_source": "authoritative.org",
                        "domain_rating_source": 75.0,
                        "url_rating_source": 24.0,
                        "anchor": "verified guide",
                        "is_dofollow": True,
                        "is_spam": False,
                        "first_seen_link": "2024-02-10T14:20:00Z",
                    },
                    {
                        "url_from": "https://spammy-site.com/links",
                        "name_source": "spammy-site.com",
                        "domain_rating_source": 4.0,
                        "url_rating_source": 2.0,
                        "anchor": "visit",
                        "is_dofollow": False,
                        "is_spam": True,
                        "first_seen_link": "2024-05-01 09:10:00",
                    },
                ]
            }
        return {}

    with patch.object(client, "_get_endpoint", side_effect=mock_endpoint):
        res = await client.fetch_offpage_signals("https://example.com/target")
        assert res["linking_pages"] is not None
        assert len(res["linking_pages"]) == 2

        lp1 = res["linking_pages"][0]
        assert lp1["domain"] == "authoritative.org"
        assert lp1["domain_rating"] == 75.0
        assert lp1["url_rating"] == 24.0
        assert lp1["anchor"] == "verified guide"
        assert lp1["dofollow"] is True
        assert lp1["spam"] is False
        assert lp1["first_seen"] == "2024-02-10"

        lp2 = res["linking_pages"][1]
        assert lp2["domain"] == "spammy-site.com"
        assert lp2["domain_rating"] == 4.0
        assert lp2["url_rating"] == 2.0
        assert lp2["anchor"] == "visit"
        assert lp2["dofollow"] is False
        assert lp2["spam"] is True
        assert lp2["first_seen"] == "2024-05-01"


@pytest.mark.asyncio
async def test_ahrefs_client_linking_pages_null_on_failure():
    client = AhrefsClient(api_key="test-key")

    async def mock_endpoint(cl, endpoint, params, headers):
        if "backlinks-stats" in endpoint:
            return {"metrics": {"live": 10, "live_refdomains": 5, "all_time_refdomains": 10}}
        elif "all-backlinks" in endpoint:
            return None  # Failure
        return {}

    with patch.object(client, "_get_endpoint", side_effect=mock_endpoint):
        res = await client.fetch_offpage_signals("https://example.com/target")
        assert res["linking_pages"] is None
        assert res["backlinks"] == 10


def test_low_authority_recommendation_rule():
    # 1. More than half low authority (spam or DR < 10) -> rule triggers
    linking_pages_low = [
        {"domain": "site1.com", "domain_rating": 5.0, "spam": False},
        {"domain": "site2.com", "domain_rating": 8.0, "spam": False},
        {"domain": "strong.com", "domain_rating": 60.0, "spam": False},
    ]
    recs_en = generate_ahrefs_recommendations(linking_pages=linking_pages_low, language="en")
    assert "Most sites linking to this page have little authority. Focus on earning links from relevant, established sites." in recs_en

    recs_es = generate_ahrefs_recommendations(linking_pages=linking_pages_low, language="es")
    assert "La mayoría de los sitios que enlazan a esta página tienen poca autoridad. Céntrate en conseguir enlaces de sitios relevantes y consolidados." in recs_es

    # Spam counts towards low authority even if DR >= 10
    linking_pages_spam = [
        {"domain": "spam1.com", "domain_rating": 50.0, "spam": True},
        {"domain": "spam2.com", "domain_rating": 2.0, "spam": False},
        {"domain": "good.com", "domain_rating": 45.0, "spam": False},
    ]
    recs_spam = generate_ahrefs_recommendations(linking_pages=linking_pages_spam, language="en")
    assert any("little authority" in r for r in recs_spam)

    # 2. More than half strong (DR >= 10, not spam) -> rule does NOT trigger
    linking_pages_high = [
        {"domain": "strong1.com", "domain_rating": 40.0, "spam": False},
        {"domain": "strong2.com", "domain_rating": 65.0, "spam": False},
        {"domain": "weak.com", "domain_rating": 5.0, "spam": False},
    ]
    recs_high = generate_ahrefs_recommendations(linking_pages=linking_pages_high, language="en")
    assert not any("little authority" in r for r in recs_high)


def test_docx_includes_linking_pages_table():
    audit_res = make_test_audit_response()
    offpage_data = AhrefsOffpageResponse(
        domain_rating=50.0,
        url_rating=15.0,
        referring_domains=12,
        backlinks=40,
        checked_at="2026-10-05T00:00:00Z",
        recommendations=["Some recommendation"],
        linking_pages=[
            {
                "url_from": "https://partner.com/article",
                "domain": "partner.com",
                "domain_rating": 55.0,
                "url_rating": 12.0,
                "anchor": "partner link",
                "dofollow": True,
                "spam": False,
                "first_seen": "2024-01-15",
            },
            {
                "url_from": "https://spammer.org/junk",
                "domain": "spammer.org",
                "domain_rating": 3.0,
                "url_rating": 1.0,
                "anchor": "click here",
                "dofollow": False,
                "spam": True,
                "first_seen": "2024-03-20",
            },
        ],
    )
    docx_bytes = generate_editor_brief_docx(
        audit_result=audit_res,
        ahrefs_offpage=offpage_data,
    )
    doc = docx.Document(io.BytesIO(docx_bytes))
    doc_text = " ".join([p.text for p in doc.paragraphs])
    assert "Who links to this page:" in doc_text

    table_cells = [cell.text for t in doc.tables for row in t.rows for cell in row.cells]
    assert "partner.com" in table_cells
    assert "spammer.org [Spam]" in table_cells
    assert "partner link" in table_cells
    assert "2024-01-15" in table_cells

