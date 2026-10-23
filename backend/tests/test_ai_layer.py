import pytest
import json
import hashlib
import asyncio
from typing import List, Dict, Any, Optional
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from config.settings import Settings, get_settings
from src.services.llm_client import (
    LLMClient,
    DailyLimitExceededError,
    LLMClientError,
    extract_json_from_text,
    daily_tracker,
)
from main import app, ai_fixes_cache, reset_failed_auth_attempts
from src.services.serp_client import serp_daily_tracker


@pytest.fixture(autouse=True)
def reset_state():
    daily_tracker.reset_for_tests()
    serp_daily_tracker.reset_for_tests()
    reset_failed_auth_attempts()
    ai_fixes_cache.clear()
    get_settings.cache_clear()
    yield
    daily_tracker.reset_for_tests()
    serp_daily_tracker.reset_for_tests()
    reset_failed_auth_attempts()
    ai_fixes_cache.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. extract_json_from_text tests
# ---------------------------------------------------------------------------

def test_extract_json_direct():
    text = '{"json_ld": {"@type": "Article"}, "lead_paragraph": {"suggested": "Hello"}}'
    res = extract_json_from_text(text)
    assert res["json_ld"]["@type"] == "Article"
    assert res["lead_paragraph"]["suggested"] == "Hello"


def test_extract_json_with_markdown_fences():
    text = """Here is your requested response:
```json
{
  "json_ld": {
    "@type": "NewsArticle",
    "headline": "Breaking news"
  },
  "lead_paragraph": {
    "suggested": "Optimized lead."
  }
}
```
Hope this helps!"""
    res = extract_json_from_text(text)
    assert res["json_ld"]["@type"] == "NewsArticle"
    assert res["lead_paragraph"]["suggested"] == "Optimized lead."


def test_extract_json_surrounding_text_no_fences():
    text = 'Sure, here is the output: {"json_ld": {"@type": "Product"}, "lead_paragraph": {"suggested": "Buy now"}} done!'
    res = extract_json_from_text(text)
    assert res["json_ld"]["@type"] == "Product"
    assert res["lead_paragraph"]["suggested"] == "Buy now"


def test_extract_json_invalid():
    with pytest.raises(LLMClientError):
        extract_json_from_text("This is not json at all")


# ---------------------------------------------------------------------------
# 2. DailyCallTracker & LLMClient tests
# ---------------------------------------------------------------------------

def test_daily_call_tracker_limit():
    daily_tracker.reset_for_tests()
    assert daily_tracker.check_and_increment(2) == 1
    assert daily_tracker.check_and_increment(2) == 2
    with pytest.raises(DailyLimitExceededError):
        daily_tracker.check_and_increment(2)


@pytest.mark.asyncio
async def test_llm_client_unconfigured():
    client = LLMClient(base_url="", model="", api_key="")
    with pytest.raises(LLMClientError, match="AI layer is not configured"):
        await client.call_chat_completion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_llm_client_retry_on_429():
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
    )

    mock_resp_429 = httpx.Response(429, json={"error": "Rate limit exceeded"})
    mock_resp_200 = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"choices": [{"message": {"content": '{"json_ld": {"@type": "Article"}}'}}]}
    )

    with patch("httpx.AsyncClient.send", side_effect=[mock_resp_429, mock_resp_200]) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await client.call_chat_completion([{"role": "user", "content": "hello"}])
        assert res["json_ld"]["@type"] == "Article"
        assert mock_send.call_count == 2
        mock_sleep.assert_called_once_with(3.0)


@pytest.mark.asyncio
async def test_llm_client_error_sanitization():
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="SUPER_SECRET_KEY_123",
        daily_limit=10,
    )

    mock_resp_500 = httpx.Response(500, text="Internal error with SUPER_SECRET_KEY_123")

    with patch("httpx.AsyncClient.send", side_effect=[mock_resp_500, mock_resp_500]), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMClientError) as exc_info:
            await client.call_chat_completion([{"role": "user", "content": "hi"}])
        assert "SUPER_SECRET_KEY_123" not in str(exc_info.value)
        assert "error status 500" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Settings ai_enabled property
# ---------------------------------------------------------------------------

def test_settings_ai_enabled():
    s = Settings(llm_base_url="", llm_model="", llm_api_key="")
    assert s.ai_enabled is False

    s2 = Settings(llm_base_url="https://api.deepseek.com", llm_model="", llm_api_key="key")
    assert s2.ai_enabled is False

    s3 = Settings(llm_base_url="https://api.deepseek.com", llm_model="deepseek-chat", llm_api_key="")
    assert s3.ai_enabled is False

    s4 = Settings(llm_base_url="https://api.deepseek.com", llm_model="deepseek-chat", llm_api_key="sk-12345")
    assert s4.ai_enabled is True
    # Verify api key is masked in repr
    assert "sk-12345" not in repr(s4)


# ---------------------------------------------------------------------------
# 4. API Endpoints: /api/version, /api/ai/fixes
# ---------------------------------------------------------------------------

client = TestClient(app)

def test_api_version_returns_ai_enabled():
    mock_settings_disabled = Settings(llm_base_url="", llm_model="", llm_api_key="")
    with patch("main.get_settings", return_value=mock_settings_disabled), \
         patch("main.settings", mock_settings_disabled):
        res = client.get("/api/version")
        assert res.status_code == 200
        assert res.json()["ai_enabled"] is False

    mock_settings_enabled = Settings(llm_base_url="https://api.ai.com", llm_model="m", llm_api_key="k")
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled):
        res = client.get("/api/version")
        assert res.status_code == 200
        assert res.json()["ai_enabled"] is True


def test_ai_fixes_503_when_disabled():
    mock_settings_disabled = Settings(llm_base_url="", llm_model="", llm_api_key="")
    with patch("main.get_settings", return_value=mock_settings_disabled), \
         patch("main.settings", mock_settings_disabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_disabled):
        res = client.post("/api/ai/fixes", json={"ai_context": {"language": "en", "content_type": "guide_blog", "main_text": "sample"}})
        assert res.status_code == 503
        assert res.json()["detail"] == "AI layer is not configured"


def test_ai_fixes_429_when_daily_limit_reached():
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_daily_limit=1,
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):
        # Fill tracker to limit
        daily_tracker.check_and_increment(1)
        res = client.post(
            "/api/ai/fixes",
            json={
                "ai_context": {
                    "url": "https://example.com/page",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "sample text",
                }
            }
        )
        assert res.status_code == 429
        assert "Daily AI limit reached" in res.json()["detail"]


def test_ai_fixes_success_overwrites_known_fields_and_validates_type():
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {
                "@context": "http://wrong-context.com",
                "@type": "RandomWrongType",
                "headline": "Hallucinated Headline",
                "url": "https://hallucinated.com",
                "datePublished": "2020-01-01",
                "author": {"@type": "Person", "name": "Fake Author"},
                "publisher": {"@type": "Organization", "name": "Fake Pub"},
            },
            "lead_paragraph": {
                "original": "Old intro text.",
                "suggested": "Optimized lead paragraph answering user intent directly.",
                "rationale": "Direct answer first.",
            }
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            req_payload = {
                "ai_context": {
                    "url": "https://example.com/guide",
                    "title": "Real Page Title",
                    "h1": "Real H1 Heading",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "The real main text content.",
                    "first_paragraph": "Old intro text.",
                    "detected_author": "Real Author Name",
                    "detected_date_published": "2026-03-25T10:00:00Z",
                    "detected_date_modified": "2026-03-26T10:00:00Z",
                    "detected_publisher": "Example Publisher",
                    "failing_submetrics": [
                        {"name": "Date Currency", "score": 40.0, "recommendation": "Update date"}
                    ]
                }
            }

            res = client.post("/api/ai/fixes", json=req_payload)
            assert res.status_code == 200
            data = res.json()

            json_ld = data["json_ld"]
            # 1. @context strictly https://schema.org
            assert json_ld["@context"] == "https://schema.org"
            # 2. @type forced to allowed type for guide_blog (Article)
            assert json_ld["@type"] == "Article"
            # 3. Known fields overwritten with extracted data (H1 preferred for headline)
            assert json_ld["headline"] == "Real H1 Heading"
            assert json_ld["url"] == "https://example.com/guide"
            assert json_ld["datePublished"] == "2026-03-25T10:00:00Z"
            assert json_ld["dateModified"] == "2026-03-26T10:00:00Z"
            assert json_ld["author"]["name"] == "Real Author Name"
            assert json_ld["publisher"]["name"] == "Example Publisher"
            # 4. Image placeholder added
            assert json_ld["image"] == "REPLACE_WITH_IMAGE_URL"
            # 5. Lead paragraph
            assert data["lead_paragraph"]["suggested"] == "Optimized lead paragraph answering user intent directly."
            assert data["lead_paragraph"]["rationale"] == "Direct answer first."


def test_ai_fixes_24h_caching():
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {"@context": "https://schema.org", "@type": "NewsArticle"},
            "lead_paragraph": {"suggested": "News lead", "rationale": "Rationale"},
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            req_payload = {
                "ai_context": {
                    "url": "https://example.com/news",
                    "title": "Breaking News",
                    "language": "en",
                    "content_type": "news",
                    "main_text": "A major event happened today.",
                }
            }

            # First call -> triggers LLM
            res1 = client.post("/api/ai/fixes", json=req_payload)
            assert res1.status_code == 200
            assert mock_call.call_count == 1

            # Second call with same url & main_text -> serves from cache without calling LLM
            res2 = client.post("/api/ai/fixes", json=req_payload)
            assert res2.status_code == 200
            assert mock_call.call_count == 1


# ---------------------------------------------------------------------------
# 5. AuditResponse ai_context inclusion / exclusion
# ---------------------------------------------------------------------------

def test_audit_endpoint_includes_ai_context_when_enabled():
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.audit_service.get_settings", return_value=mock_settings_enabled):
        res = client.post(
            "/api/audit",
            json={"content_text": "This is a detailed guide about Python programming and machine learning with sufficient length to test the pipeline thoroughly."}
        )
        assert res.status_code == 200
        data = res.json()
        assert "ai_context" in data
        assert data["ai_context"] is not None
        assert "main_text" in data["ai_context"]


def test_audit_endpoint_omits_ai_context_when_disabled():
    mock_settings_disabled = Settings(llm_base_url="", llm_model="", llm_api_key="")
    with patch("main.get_settings", return_value=mock_settings_disabled), \
         patch("main.settings", mock_settings_disabled), \
         patch("src.services.audit_service.get_settings", return_value=mock_settings_disabled):
        res = client.post(
            "/api/audit",
            json={"content_text": "This is a detailed guide about Python programming and machine learning with sufficient length to test the pipeline thoroughly."}
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("ai_context") is None


# ---------------------------------------------------------------------------
# 6. New tests requested in task corrections
# ---------------------------------------------------------------------------

def test_ai_fixes_undetected_fields_use_placeholders_and_ignore_hallucinations():
    """
    If author, dates, and publisher are not detected, hallucinated values from LLM
    must be replaced by strict placeholders.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": "LLM Headline",
                "author": {"@type": "Person", "name": "Hallucinated John Doe"},
                "datePublished": "2023-01-01T00:00:00Z",
                "dateModified": "2023-01-02T00:00:00Z",
                "publisher": {"@type": "Organization", "name": "Hallucinated Media Inc"},
            },
            "lead_paragraph": {
                "original": "Old text.",
                "suggested": "Optimized lead.",
                "rationale": "Direct answer.",
            }
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            req_payload = {
                "ai_context": {
                    "url": "https://example.com/post",
                    "title": "Real Title",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "Sample content without any metadata.",
                    "detected_author": None,
                    "detected_date_published": None,
                    "detected_date_modified": None,
                    "detected_publisher": None,
                }
            }

            res = client.post("/api/ai/fixes", json=req_payload)
            assert res.status_code == 200
            json_ld = res.json()["json_ld"]

            assert json_ld["author"]["name"] == "REPLACE_WITH_AUTHOR_NAME"
            assert json_ld["datePublished"] == "REPLACE_WITH_DATE_PUBLISHED"
            assert json_ld["dateModified"] == "REPLACE_WITH_DATE_MODIFIED"
            assert json_ld["publisher"] == {"@type": "Organization", "name": "REPLACE_WITH_PUBLISHER_NAME"}


def test_ai_fixes_username_author_warning():
    """
    Author with username pattern generates warning; normal name does not.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {"@context": "https://schema.org", "@type": "Article"},
            "lead_paragraph": {"suggested": "Lead", "rationale": "Rationale"},
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            # Case 1: marcos.perez -> username warning
            res1 = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/post1",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "Content 1",
                    "detected_author": "marcos.perez",
                }
            })
            assert res1.status_code == 200
            data1 = res1.json()
            assert data1["json_ld"]["author"]["name"] == "marcos.perez"
            assert any("looks like a username" in w for w in data1["warnings"])

            # Case 2: Marcos Pérez -> no username warning
            res2 = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/post2",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "Content 2",
                    "detected_author": "Marcos Pérez",
                }
            })
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["json_ld"]["author"]["name"] == "Marcos Pérez"
            assert not any("looks like a username" in w for w in data2["warnings"])


def test_publisher_extraction_priority_and_domain_warning():
    """
    Publisher prioritized: JSON-LD existing Organization > og:site_name > domain.
    When inferred from domain, adds warning in AI fixes.
    """
    from src.services.audit_service import _build_ai_context
    from src.models.schemas import PageData

    # Case A: JSON-LD has Organization
    html_json_ld = """
    <html>
      <head>
        <meta property="og:site_name" content="OG Name" />
        <script type="application/ld+json">
          {"@context": "https://schema.org", "@type": "NewsArticle", "publisher": {"@type": "Organization", "name": "JSONLD Org"}}
        </script>
      </head>
      <body><h1>Title</h1><p>Body text</p></body>
    </html>
    """
    page_a = PageData(
        url="https://example.com/article",
        final_url="https://example.com/article",
        html_raw=html_json_ld,
        html_rendered=html_json_ld,
        text_content="Title Body text",
        status_code=200,
        load_time_ms=50.0,
    )
    ctx_a = _build_ai_context(page_a, [], "en", "news", "https://example.com/article")
    assert ctx_a.detected_publisher == "JSONLD Org"
    assert ctx_a.publisher_inferred_from_domain is False

    # Case B: No JSON-LD, has og:site_name
    html_og = """
    <html>
      <head>
        <meta property="og:site_name" content="OG Site Name" />
      </head>
      <body><h1>Title</h1><p>Body text</p></body>
    </html>
    """
    page_b = PageData(
        url="https://example.com/article",
        final_url="https://example.com/article",
        html_raw=html_og,
        html_rendered=html_og,
        text_content="Title Body text",
        status_code=200,
        load_time_ms=50.0,
    )
    ctx_b = _build_ai_context(page_b, [], "en", "news", "https://example.com/article")
    assert ctx_b.detected_publisher == "OG Site Name"
    assert ctx_b.publisher_inferred_from_domain is False

    # Case C: Neither JSON-LD nor meta, inferred from domain
    html_bare = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
    page_c = PageData(
        url="https://www.example-domain.org/article",
        final_url="https://www.example-domain.org/article",
        html_raw=html_bare,
        html_rendered=html_bare,
        text_content="Title Body text",
        status_code=200,
        load_time_ms=50.0,
    )
    ctx_c = _build_ai_context(page_c, [], "en", "news", "https://www.example-domain.org/article")
    assert ctx_c.detected_publisher == "example-domain.org"
    assert ctx_c.publisher_inferred_from_domain is True

    # When sending ctx_c to /api/ai/fixes, should have warning
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):
        llm_mock_return = {
            "json_ld": {"@context": "https://schema.org", "@type": "NewsArticle"},
            "lead_paragraph": {"suggested": "News lead", "rationale": "Rationale"},
        }
        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return
            res = client.post("/api/ai/fixes", json={"ai_context": ctx_c.model_dump()})
            assert res.status_code == 200
            assert any("Publisher name inferred from domain" in w for w in res.json()["warnings"])


def test_ai_fixes_product_uses_name_and_no_headline():
    """
    For Product or Review, uses 'name' instead of 'headline', and headline is removed.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Product",
                "headline": "Should Be Removed",
                "name": "Old Product",
            },
            "lead_paragraph": {"suggested": "Lead", "rationale": "Rationale"},
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/product",
                    "title": "Super Gadget X",
                    "language": "en",
                    "content_type": "product",
                    "main_text": "Buy Super Gadget X with great battery life.",
                }
            })
            assert res.status_code == 200
            json_ld = res.json()["json_ld"]
            assert json_ld["@type"] == "Product"
            assert json_ld["name"] == "Super Gadget X"
            assert "headline" not in json_ld


def test_ai_fixes_cache_capacity_cap_at_100():
    """
    The in-memory cache ai_fixes_cache must never exceed 100 entries.
    Oldest entries are evicted upon insertion.
    """
    from main import put_ai_fixes_cache

    ai_fixes_cache.clear()
    for i in range(120):
        put_ai_fixes_cache(f"key_{i}", {"data": i}, 9999999999.0)

    assert len(ai_fixes_cache) == 100
    # First 20 items (0 to 19) should have been evicted
    assert "key_0" not in ai_fixes_cache
    assert "key_19" not in ai_fixes_cache
    assert "key_20" in ai_fixes_cache
    assert "key_119" in ai_fixes_cache


def test_audit_scores_identical_with_and_without_ai():
    """
    Core principle: The AI layer NEVER alters the overall score or any dimension score.
    Compare /api/audit output for identical content with AI enabled vs AI disabled.
    """
    synthetic_content = """
    # Complete Guide to Artificial Intelligence Optimization

    Artificial intelligence is revolutionizing the way search engines retrieve and present information.
    In this guide, we analyze how Large Language Models like ChatGPT and Gemini evaluate authority.

    ## Key Statistical Findings
    According to our 2026 benchmark study, structured data increases citation probability by 42 percent.
    Therefore, implementing Schema.org markup is critical for modern content creators.

    ## Implementation Steps
    First, ensure all technical headers are in place.
    Second, cite original studies with verifiable evidence.
    Third, provide concise, standalone answers directly at the beginning of each section.
    """

    mock_settings_disabled = Settings(llm_base_url="", llm_model="", llm_api_key="")
    with patch("main.get_settings", return_value=mock_settings_disabled), \
         patch("main.settings", mock_settings_disabled), \
         patch("src.services.audit_service.get_settings", return_value=mock_settings_disabled):
        res_disabled = client.post("/api/audit", json={"content_text": synthetic_content})
        assert res_disabled.status_code == 200
        data_disabled = res_disabled.json()

    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.audit_service.get_settings", return_value=mock_settings_enabled):
        res_enabled = client.post("/api/audit", json={"content_text": synthetic_content})
        assert res_enabled.status_code == 200
        data_enabled = res_enabled.json()

    # Scores must match precisely
    assert data_disabled["total_score"] == data_enabled["total_score"]
    assert len(data_disabled["dimensions"]) == len(data_enabled["dimensions"])
    for dim_d, dim_e in zip(data_disabled["dimensions"], data_enabled["dimensions"]):
        assert dim_d["name"] == dim_e["name"]
        assert dim_d["score"] == dim_e["score"]
        assert dim_d["weight"] == dim_e["weight"]
        assert dim_d["contribution"] == dim_e["contribution"]

    # detector_results scores must match precisely
    for det_d, det_e in zip(data_disabled["detector_results"], data_enabled["detector_results"]):
        assert det_d["dimension"] == det_e["dimension"]
        assert det_d["score"] == det_e["score"]
        assert det_d["weight"] == det_e["weight"]
        assert det_d["contribution"] == det_e["contribution"]

    # Only ai_context should differ
    assert data_disabled.get("ai_context") is None
    assert data_enabled.get("ai_context") is not None


# ---------------------------------------------------------------------------
# 5. Phase 6b Tests: Parte A, B, C, D
# ---------------------------------------------------------------------------

def test_author_organization_detection():
    """
    If author matches publisher, domain or has domain TLD, it should be typed as Organization,
    not trigger username warning, and add organization author note.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "json_ld": {},
                "lead_paragraph": {"suggested": "Optimized lead."}
            }

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://company.com/blog/news",
                    "title": "Company News",
                    "detected_author": "company.com",
                    "detected_publisher": "Company Inc",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "Sample content text.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert data["json_ld"]["author"] == {"@type": "Organization", "name": "company.com"}
            assert any("The author is the organization itself" in w for w in data["warnings"])
            assert not any("looks like a username" in w for w in data["warnings"])


def test_author_username_warning():
    """
    Username-style author (like marcos.perez) keeps Person type and shows username warning.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "json_ld": {},
                "lead_paragraph": {"suggested": "Optimized lead."}
            }

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/post",
                    "title": "Post Title",
                    "detected_author": "marcos.perez",
                    "detected_publisher": "Example Blog",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "Sample content text.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert data["json_ld"]["author"] == {"@type": "Person", "name": "marcos.perez"}
            assert any("looks like a username" in w for w in data["warnings"])


def test_clean_headline_strips_suffix_and_clamps():
    """
    compute_clean_headline strips site suffix and prefers H1.
    """
    from main import compute_clean_headline
    from src.models.schemas import AIContext

    ctx_h1 = AIContext(
        h1="Essential GEO Best Practices for 2026",
        title="Essential GEO Best Practices for 2026 - My Brand Website",
        language="en",
        content_type="guide_blog",
        main_text="Some text",
    )
    assert compute_clean_headline(ctx_h1) == "Essential GEO Best Practices for 2026"

    ctx_title_strip = AIContext(
        h1="",
        title="Comprehensive AI Search Engine Optimization Guide | TechPortal.com",
        language="en",
        content_type="guide_blog",
        main_text="Some text",
    )
    assert compute_clean_headline(ctx_title_strip) == "Comprehensive AI Search Engine Optimization Guide"


def test_ai_fixes_includes_detected_image():
    """
    If detected_image_url is present, Schema.org json-ld has that image instead of placeholder.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "json_ld": {},
                "lead_paragraph": {"suggested": "Optimized lead."}
            }

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/post",
                    "title": "Post Title",
                    "detected_image_url": "https://example.com/images/hero.jpg",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "Sample text",
                }
            })
            assert res.status_code == 200
            assert res.json()["json_ld"]["image"] == "https://example.com/images/hero.jpg"


@pytest.mark.asyncio
async def test_ai_plan_endpoint_success_and_validation():
    """
    Test /api/ai/plan with numerical validation, stripping invented figures,
    combined schema, and url stripping.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        mock_plan_return = {
            "questions_to_answer": [
                {
                    "question": "What is the ROI?",
                    "draft_answer": "The conversion rate reached 42 percent across tests https://fake.com/link.",
                    "answer_source": "page"
                },
                {
                    "question": "What is the hallucinated figure?",
                    "draft_answer": "Revenue grew by 999 percent in 2029.",
                    "answer_source": "page"
                }
            ],
            "suggested_h2_structure": [
                {
                    "h2": "Direct Strategy Implementation",
                    "purpose": "Answers user how-to queries",
                    "status": "new"
                }
            ],
            "suggested_table": {
                "title": "Performance Metrics",
                "headers": ["Metric", "Value"],
                "rows": [
                    ["Valid Conversion", "42 percent"],
                    ["Hallucinated Value", "99999 dollars"]
                ]
            },
            "data_opportunities": [
                {
                    "suggestion": "Include benchmark for standard latency",
                    "source_type": "Industry Benchmark"
                },
                {
                    "suggestion": "Invented metric with 888 percent growth",
                    "source_type": "Bogus"
                }
            ],
            "paragraphs_to_add": [
                {
                    "target_issue": "Missing direct answer",
                    "suggested_text": "Implementing direct answer blocks helps reach the 42 percent threshold https://badlink.com.",
                    "placement": "Under the first H2"
                }
            ]
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_plan_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/guide",
                    "title": "GEO Guide 2026",
                    "h1": "GEO Guide 2026",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "In this guide we test conversion rate of 42 percent across 100 pages.",
                }
            })
            assert res.status_code == 200
            data = res.json()

            # 1. Questions: only question with 42 percent preserved; question with 999 percent removed
            assert len(data["questions_to_answer"]) == 1
            assert data["questions_to_answer"][0]["question"] == "What is the ROI?"
            assert "https://" not in data["questions_to_answer"][0]["draft_answer"]

            # 2. Table: row with 99999 removed, leaving 1 row (<2 rows), so table defaults to idea
            assert data["suggested_table"]["rows"] is None
            assert data["suggested_table"]["table_idea"] is not None

            # 3. Data opps: bogus 888 percent removed
            assert len(data["data_opportunities"]) == 1
            assert "standard latency" in data["data_opportunities"][0]["suggestion"]

            # 4. Paragraphs: url stripped, valid
            assert len(data["paragraphs_to_add"]) == 1
            assert "https://" not in data["paragraphs_to_add"][0]["suggested_text"]

            # 5. Combined schema check: @graph has Article, FAQPage, Organization
            graph = data["combined_schema"].get("@graph", [])
            types = [item.get("@type") for item in graph]
            assert "Article" in types
            assert "FAQPage" in types
            assert "Organization" in types

            # 6. Warnings check
            assert any("suggestions were removed because they contained figures" in w for w in data["warnings"])


def test_links_unwrap_redirect():
    """
    Proofpoint v2, v3 and Outlook Safe Links are properly unwrapped.
    """
    from src.detectors.links import unwrap_redirect_url

    # Proofpoint v3
    v3 = "https://urldefense.com/v3/__https://securitize.io/about__;!!xyz!123$"
    assert unwrap_redirect_url(v3) == "https://securitize.io/about"

    # Proofpoint v2
    v2 = "https://urldefense.proofpoint.com/v2/url?u=https-3A__example.com_doc&d=123"
    assert unwrap_redirect_url(v2) == "https://example.com/doc"

    # Outlook safelinks
    safe = "https://eur01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fpartner.com%2Fnews&data=abc"
    assert unwrap_redirect_url(safe) == "https://partner.com/news"

    # Normal url unchanged
    normal = "https://example.com/normal"
    assert unwrap_redirect_url(normal) == normal


@pytest.mark.asyncio
async def test_aeo_heading_structure_score_and_detected_headers_with_h4():
    """
    Checks that:
    1. A page with 1 H2, 1 H3, and 3 H4 gives the exact same Heading Structure score as in main (raw_score=60.0, weighted_score=15.0).
    2. detected_headers contains only H2 and H3, excluding H4.
    3. header_count equals len(detected_headers).
    4. With socios fixture, detected_headers includes 'About Socios.com' and 'About Securitize'.
    """
    from src.detectors.aeo_structure import AEOStructureDetector
    from src.models.schemas import PageData

    detector = AEOStructureDetector()
    html = """
    <html><body><article>
    <h1>Main Article Title</h1>
    <p>""" + ("word " * 250) + """</p>
    <h2>Main H2 Heading</h2>
    <p>""" + ("word " * 250) + """</p>
    <h3>Subsection H3</h3>
    <p>""" + ("word " * 200) + """</p>
    <h4>Detail H4 A</h4>
    <p>detail</p>
    <h4>Detail H4 B</h4>
    <p>detail</p>
    <h4>Detail H4 C</h4>
    <p>detail</p>
    </article></body></html>
    """
    page_data = PageData(
        url="https://example.com/headers",
        final_url="https://example.com/headers",
        html_raw=html,
        html_rendered=html,
        text_content="Some text",
        status_code=200,
        load_time_ms=100.0,
    )
    res = await detector.analyze(page_data)
    heading_breakdown = [b for b in res.breakdown if b.name == "Heading Structure"][0]
    
    # Exact main baseline values (1 H2 for ~720 words -> raw 50.0 + 10.0 H3 bonus = 60.0)
    assert heading_breakdown.raw_score == 60.0
    assert heading_breakdown.weighted_score == 15.0
    assert "Bonus: 1 H3s detected." in heading_breakdown.explanation
    assert "H4" not in heading_breakdown.explanation

    # detected_headers only H2 and H3, no H4
    assert res.debug_info["detected_headers"] == ["Main H2 Heading", "Subsection H3"]
    assert res.debug_info["header_count"] == 2
    assert "Detail H4 A" not in res.debug_info["detected_headers"]

    # Socios fixture check
    with open("tests/fixtures/socios_securitize.html", "r", encoding="utf-8") as f:
        socios_html = f.read()

    socios_page = PageData(
        url="https://example.com/socios",
        final_url="https://example.com/socios",
        html_raw=socios_html,
        html_rendered=socios_html,
        text_content="",
        status_code=200,
        load_time_ms=100.0,
    )
    socios_res = await detector.analyze(socios_page)
    socios_detected = socios_res.debug_info["detected_headers"]
    assert "About Socios.com" in socios_detected
    assert "About Securitize" in socios_detected


def test_ai_fixes_lead_with_unverified_figures_fallback_and_warning():
    """
    Test 1: Invented figure in suggested lead falls back to original lead and adds specific warning.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": "Test Headline",
            },
            "lead_paragraph": {
                "suggested": "This article claims revenue grew by 999 percent in Q4.",
                "rationale": "Optimized lead",
            },
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/article",
                    "title": "Test Headline",
                    "language": "en",
                    "content_type": "guide_blog",
                    "first_paragraph": "Original safe paragraph with no numbers.",
                    "main_text": "Original safe paragraph with no numbers. General body text without any figures.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert data["lead_paragraph"]["suggested"] == "Original safe paragraph with no numbers."
            assert "The suggested lead contained figures not found on the page and was discarded." in data["warnings"]


def test_ai_fixes_mentions_and_about_unverified_figures_removed_and_warned():
    """
    Test 2: Mention/about with invented figure is removed and adds warning.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": "Test Headline",
                "description": "Safe description",
                "about": [
                    {"@type": "Thing", "name": "Topic 8888"},
                    {"@type": "Thing", "name": "Valid Topic"},
                ],
                "mentions": [
                    {"@type": "Thing", "name": "Fake 9999 Corp"},
                ],
            },
            "lead_paragraph": {
                "suggested": "Clean lead without unverified numbers.",
                "rationale": "Rationale",
            },
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/fixes", json={
                "ai_context": {
                    "url": "https://example.com/article",
                    "title": "Test Headline",
                    "language": "en",
                    "content_type": "guide_blog",
                    "first_paragraph": "Original lead.",
                    "main_text": "Original lead. Valid Topic is discussed here.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            about_names = [a["name"] for a in data["json_ld"].get("about", [])]
            assert "Valid Topic" in about_names
            assert "Topic 8888" not in about_names
            assert len(data["json_ld"].get("mentions", [])) == 0
            assert any("Schema.org elements were removed because they contained figures not found on the page" in w for w in data["warnings"])


def test_ai_plan_caps_outline_to_seven():
    """
    Test 3: Outline of 9 items returned by mock LLM is capped to exactly 7.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "questions_to_answer": [],
            "suggested_h2_structure": [
                {"h2": f"Section {i}", "purpose": f"Purpose {i}", "status": "new"}
                for i in range(1, 10)
            ],
            "data_opportunities": [],
            "paragraphs_to_add": [],
            "inconsistencies": [],
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/article",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "Texto del artículo base.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert len(data["suggested_h2_structure"]) == 7
            assert data["suggested_h2_structure"][0]["h2"] == "Section 1"
            assert data["suggested_h2_structure"][6]["h2"] == "Section 7"


def test_ai_plan_combined_schema_no_nested_context():
    """
    Test 4: Combined schema has '@context' only at the root, no nested '@context' inside '@graph'.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "questions_to_answer": [
                {"question": "¿Qué es?", "draft_answer": "Respuesta breve.", "answer_source": "page"}
            ],
            "suggested_h2_structure": [],
            "data_opportunities": [],
            "paragraphs_to_add": [],
            "inconsistencies": [],
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/schema-test",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "Respuesta breve. Más texto aquí.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            combined = data["combined_schema"]
            assert combined["@context"] == "https://schema.org"
            assert "@graph" in combined
            for item in combined["@graph"]:
                assert "@context" not in item


def test_ai_plan_strips_verification_phrases_from_suggested_paragraph():
    """
    Test 5: Editorial verification sentences are stripped from suggested publishable paragraphs.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "questions_to_answer": [],
            "suggested_h2_structure": [],
            "data_opportunities": [],
            "paragraphs_to_add": [
                {
                    "target_issue": "Falta de claridad",
                    "suggested_text": "El sistema proporciona alta disponibilidad. Habría que comprobar con el equipo técnico. Ofrece soporte 24/7.",
                    "placement": "Al final de la sección 1",
                },
                {
                    "target_issue": "Missing details",
                    "suggested_text": "This feature reduces latency significantly. This should be verified with benchmarks. It is ready for production.",
                    "placement": "Under section 2",
                }
            ],
            "inconsistencies": [],
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/paragraphs",
                    "language": "es",
                    "content_type": "guide_blog",
                    "main_text": "El sistema proporciona alta disponibilidad. Ofrece soporte 24/7. This feature reduces latency significantly. It is ready for production.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            paras = data["paragraphs_to_add"]
            assert len(paras) == 2
            assert "Habría que comprobar" not in paras[0]["suggested_text"]
            assert "El sistema proporciona alta disponibilidad. Ofrece soporte 24/7." == paras[0]["suggested_text"]
            assert "should be verified" not in paras[1]["suggested_text"].lower()
            assert "This feature reduces latency significantly. It is ready for production." == paras[1]["suggested_text"]


def test_ai_plan_inconsistency_kept_when_values_present_in_page():
    """
    Test 6: Inconsistency whose conflicting values are both literally present in page text is kept.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "questions_to_answer": [],
            "suggested_h2_structure": [],
            "data_opportunities": [],
            "paragraphs_to_add": [],
            "inconsistencies": [
                {
                    "issue": "Conflicting founding year",
                    "values": ["2018", "2020"],
                    "suggestion": "Verify official founding year in corporate registry",
                }
            ],
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/company",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "The company was founded in 2018 according to the header, but later text states established in 2020.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert len(data["inconsistencies"]) == 1
            assert data["inconsistencies"][0]["issue"] == "Conflicting founding year"
            assert data["inconsistencies"][0]["values"] == ["2018", "2020"]


def test_ai_plan_inconsistency_discarded_when_value_not_in_page():
    """
    Test 7: Inconsistency with a value not present in the page text is discarded.
    """
    mock_settings_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    with patch("main.get_settings", return_value=mock_settings_enabled), \
         patch("main.settings", mock_settings_enabled), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings_enabled):

        llm_mock_return = {
            "questions_to_answer": [],
            "suggested_h2_structure": [],
            "data_opportunities": [],
            "paragraphs_to_add": [],
            "inconsistencies": [
                {
                    "issue": "Conflicting founding year",
                    "values": ["2018", "1999"],
                    "suggestion": "Verify whether 1999 is correct",
                }
            ],
        }

        with patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = llm_mock_return

            res = client.post("/api/ai/plan", json={
                "ai_context": {
                    "url": "https://example.com/company",
                    "language": "en",
                    "content_type": "guide_blog",
                    "main_text": "The company was founded in 2018. No other year is mentioned.",
                }
            })
            assert res.status_code == 200
            data = res.json()
            assert len(data["inconsistencies"]) == 0


def test_serp_settings_property_and_version_endpoint():
    """
    Test 1: serp_enabled property logic, repr safety, and /api/version output.
    """
    # Case A: no credentials
    s1 = Settings(llm_base_url="https://api.openai.com/v1", llm_model="gpt-4o", llm_api_key="sk-test")
    assert s1.ai_enabled is True
    assert s1.serp_enabled is False

    # Case B: credentials but no AI
    s2 = Settings(dataforseo_login="login1", dataforseo_password="pw1")
    assert s2.ai_enabled is False
    assert s2.serp_enabled is False

    # Case C: both AI and SERP configured
    s3 = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="supersecretpassword",
    )
    assert s3.ai_enabled is True
    assert s3.serp_enabled is True
    assert "supersecretpassword" not in repr(s3)

    # Version endpoint check
    with patch("main.settings", s3):
        res = client.get("/api/version")
        assert res.status_code == 200
        data = res.json()
        assert data["ai_enabled"] is True
        assert data["serp_enabled"] is True


@pytest.mark.asyncio
async def test_serp_client_parse_exclusions_and_cache():
    """
    Test 2: DataForSEO item parsing, domain & social network exclusions, and 24h cache.
    """
    from src.services.serp_client import SerpClient, put_serp_cache_entry, serp_cache

    # Clear cache before test
    serp_cache.clear()

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )

    raw_items = [
        {
            "type": "people_also_ask",
            "items": [
                {"title": "Question 1?", "url": "https://www.example.com/faq", "domain": "example.com"},
                {"title": "Question 2?", "url": "https://twitter.com/status/123", "domain": "twitter.com"},
                {"title": "Question 3?", "url": "https://authority.org/answer", "domain": "authority.org"},
            ],
        },
        {
            "type": "ai_overview",
            "references": [
                {"title": "Internal Ref", "url": "https://example.com/about", "domain": "example.com"},
                {"title": "Social Ref", "url": "https://linkedin.com/in/carlos", "domain": "linkedin.com"},
                {"title": "AI Ref 1", "url": "https://nature.com/articles/123", "domain": "nature.com"},
            ],
        },
        {
            "type": "organic",
            "title": "Own Site",
            "url": "https://example.com/blog",
            "domain": "example.com",
        },
        {
            "type": "organic",
            "title": "Facebook Result",
            "url": "https://facebook.com/page",
            "domain": "facebook.com",
        },
    ]
    # Add 12 organic results to verify max 10 organic
    for i in range(1, 13):
        raw_items.append({
            "type": "organic",
            "title": f"Organic Title {i}",
            "url": f"https://source{i}.org/page",
            "domain": f"source{i}.org",
        })

    raw_items.append({
        "type": "related_searches",
        "items": ["related search term 1", "related search term 2"],
    })

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login123",
        dataforseo_password="password123",
    )
    client_serp = SerpClient(mock_settings)
    parsed = client_serp._parse_items(raw_items, audited_url="https://www.example.com/post", query="test query", market_display="US/en")

    # Verify People Also Ask exclusions
    assert len(parsed["people_also_ask"]) == 3
    # Question 1 had example.com -> url and domain stripped
    assert parsed["people_also_ask"][0]["question"] == "Question 1?"
    assert parsed["people_also_ask"][0]["url"] is None
    # Question 2 had twitter.com -> url and domain stripped
    assert parsed["people_also_ask"][1]["question"] == "Question 2?"
    assert parsed["people_also_ask"][1]["url"] is None
    # Question 3 had authority.org -> kept
    assert parsed["people_also_ask"][2]["question"] == "Question 3?"
    assert parsed["people_also_ask"][2]["domain"] == "authority.org"

    # Verify AI Overview exclusions
    assert len(parsed["ai_overview_sources"]) == 1
    assert parsed["ai_overview_sources"][0]["domain"] == "nature.com"

    # Verify Organic top 10 and exclusions
    assert len(parsed["organic"]) == 10
    assert not any("example.com" in o["domain"] for o in parsed["organic"])
    assert not any("facebook.com" in o["domain"] for o in parsed["organic"])
    assert parsed["organic"][0]["domain"] == "source1.org"

    # Verify Related Searches
    assert parsed["related_searches"] == ["related search term 1", "related search term 2"]

    # Verify Caching in fetch_serp_live
    mock_response = {
        "tasks": [
            {
                "status_code": 20000,
                "result": [{"items": raw_items}],
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response, raise_for_status=lambda: None)

        # First call: hits httpx
        res1 = await client_serp.fetch_serp_live("test cache query", language="en", audited_url="https://example.com")
        assert mock_post.call_count == 1
        assert len(res1["ai_overview_sources"]) == 1

        # Second call: uses cache
        res2 = await client_serp.fetch_serp_live("test cache query", language="en", audited_url="https://example.com")
        assert mock_post.call_count == 1  # No additional HTTP call
        assert res1 == res2


@pytest.mark.asyncio
async def test_serp_client_people_also_search_expanded_element_and_async_flag():
    """
    Test SERP client requirements:
    1. people_also_search does not add to people_also_ask, but adds titles to related_searches (no dupes).
    2. PAA with expanded_element[0] url uses that url instead of sub.url.
    3. Payload sent to DataForSEO includes load_async_ai_overview: True.
    """
    from src.services.serp_client import SerpClient

    mock_settings = Settings(
        dataforseo_login="login_test",
        dataforseo_password="pw_test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client_serp = SerpClient(mock_settings)

    raw_items = [
        # PAA question where expanded_element has url & domain
        {
            "type": "people_also_ask",
            "items": [
                {
                    "title": "What is AI citability?",
                    "url": "https://fallback.com/page",
                    "domain": "fallback.com",
                    "expanded_element": [
                        {
                            "url": "https://expanded-authority.org/article",
                            "domain": "expanded-authority.org",
                        }
                    ],
                },
                # PAA question where expanded_element does not have url -> uses sub.url
                {
                    "title": "How to optimize for AEO?",
                    "url": "https://fallback-kept.com/aeo",
                    "domain": "fallback-kept.com",
                    "expanded_element": [],
                },
            ],
        },
        # people_also_search block -> must NOT be in people_also_ask, must be in related_searches
        {
            "type": "people_also_search",
            "items": [
                {"title": "ai optimization tools"},
                {"title": "how search engines cite sources"},
            ],
        },
        # standard related_searches
        {
            "type": "related_searches",
            "items": [
                "ai optimization tools",  # duplicate of people_also_search -> should not duplicate
                "future of search engines",
            ],
        },
    ]

    parsed = client_serp._parse_items(raw_items, audited_url="https://mysite.com", query="ai optimization", market_display="US/en")

    # 1. people_also_ask only has the 2 questions from people_also_ask, nothing from people_also_search
    assert len(parsed["people_also_ask"]) == 2
    assert parsed["people_also_ask"][0]["question"] == "What is AI citability?"
    # expanded_element url was chosen over fallback.com
    assert parsed["people_also_ask"][0]["url"] == "https://expanded-authority.org/article"
    assert parsed["people_also_ask"][0]["domain"] == "expanded-authority.org"

    # fallback was used when expanded_element has no url
    assert parsed["people_also_ask"][1]["question"] == "How to optimize for AEO?"
    assert parsed["people_also_ask"][1]["url"] == "https://fallback-kept.com/aeo"
    assert parsed["people_also_ask"][1]["domain"] == "fallback-kept.com"

    # 2. people_also_search titles added to related_searches, and deduplicated
    assert parsed["related_searches"] == [
        "ai optimization tools",
        "how search engines cite sources",
        "future of search engines",
    ]

    # 3. Payload sent to DataForSEO includes load_async_ai_overview: True
    mock_response = {
        "tasks": [
            {
                "status_code": 20000,
                "result": [{"items": []}],
            }
        ]
    }
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_response, raise_for_status=lambda: None)
        await client_serp.fetch_serp_live("test query", language="en", audited_url="https://mysite.com")
        assert mock_post.call_count == 1
        call_kwargs = mock_post.call_args.kwargs
        sent_json = call_kwargs.get("json")
        assert isinstance(sent_json, list) and len(sent_json) == 1
        assert sent_json[0].get("load_async_ai_overview") is True


@pytest.mark.asyncio
async def test_serp_query_resolution_target_query_llm_and_fallback():
    """
    Test 3: Query resolution priority: Target query > short LLM call > H1 trimmed to 8 words.
    """
    from src.models.schemas import AIContext
    from main import resolve_serp_query
    from src.services.llm_client import LLMClient

    mock_llm = MagicMock(spec=LLMClient)

    # Case A: Target query provided
    ctx_a = AIContext(
        url="https://example.com",
        title="Page Title",
        h1="Article Main Heading Long Long Long",
        main_text="Some text",
        target_query="explicit target keyword",
    )
    res_a = await resolve_serp_query(ctx_a, mock_llm)
    assert res_a == "explicit target keyword"

    # Case B: No target query, LLM call succeeds
    ctx_b = AIContext(
        url="https://example.com",
        title="Page Title",
        h1="Article Main Heading",
        main_text="Some text about bitcoin mining hardware.",
    )
    mock_llm.call_chat_completion = AsyncMock(return_value={"query": "best bitcoin miners 2026"})
    res_b = await resolve_serp_query(ctx_b, mock_llm)
    assert res_b == "best bitcoin miners 2026"

    # Case C: No target query, LLM call fails -> fallback to H1 trimmed to 8 words
    mock_llm.call_chat_completion = AsyncMock(side_effect=Exception("LLM timeout"))
    ctx_c = AIContext(
        url="https://example.com",
        title="Page Title",
        h1="One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve",
        main_text="Some text",
    )
    res_c = await resolve_serp_query(ctx_c, mock_llm)
    assert res_c == "One Two Three Four Five Six Seven Eight"


def test_ai_plan_serp_paa_sources_and_url_integrity():
    """
    Test 4: Questions matching PAA get origin='google_paa' and exact Google question text.
    sources_to_cite has at most 8 sources, no duplicate domains, AI Overview first,
    and URLs come solely from DataForSEO even if LLM returns different URLs.
    """
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )

    mock_serp_data = {
        "query": "seo audit guide",
        "market": "US/en",
        "people_also_ask": [
            {"question": "How do you audit website SEO?", "url": "https://authority.org/guide", "domain": "authority.org"},
        ],
        "ai_overview_sources": [
            {"url": "https://ai-ref.com/page", "title": "AI Ref Title", "domain": "ai-ref.com"},
        ],
        "organic": [
            {"url": "https://ai-ref.com/duplicate", "title": "Dup Domain", "domain": "ai-ref.com"},
            {"url": "https://organic-top.org/overview", "title": "Organic Top", "domain": "organic-top.org"},
        ],
        "related_searches": ["seo checklist"],
    }

    mock_llm_return = {
        "questions_to_answer": [
            {
                # PAA match (different casing and punctuation)
                "question": "how do you audit website seo",
                "draft_answer": "You analyze crawlability, content, and backlinks.",
                "answer_source": "page",
            },
            {
                "question": "Is this tool free?",
                "draft_answer": "Yes, a free trial is available.",
                "answer_source": "needs_info",
            },
        ],
        "suggested_h2_structure": [
            {"h2": "SEO Audit Checklist", "purpose": "Actionable steps", "status": "new"}
        ],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
        "sources_why": [
            {"index": 1, "why": "Comprehensive overview of AI citability factors.", "url": "https://hacker-fake.com/bad"},
            {"domain": "organic-top.org", "why": "Benchmark standards for technical architecture."},
        ],
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.SerpClient.fetch_serp_live", new_callable=AsyncMock) as mock_serp, \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_serp.return_value = mock_serp_data
        # First call is resolve_serp_query, second is main plan
        mock_llm.side_effect = [
            {"query": "seo audit guide"},
            mock_llm_return,
        ]

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://mysite.com/article",
                "title": "Complete SEO Audit Guide",
                "h1": "SEO Audit Guide",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "You analyze crawlability, content, and backlinks.",
            }
        })
        assert res.status_code == 200
        data = res.json()

        assert data["serp_used"] is True
        assert data["serp_query"] == "seo audit guide"
        assert data["serp_market"] == "US/en"

        # Check questions matching
        q1 = data["questions_to_answer"][0]
        assert q1["origin"] == "google_paa"
        # Must use exact Google question text with original casing/punctuation
        assert q1["question"] == "How do you audit website SEO?"

        q2 = data["questions_to_answer"][1]
        assert q2["origin"] == "ai"
        assert q2["question"] == "Is this tool free?"

        # Check sources to cite
        sources = data["sources_to_cite"]
        assert len(sources) == 2
        # First is AI Overview
        assert sources[0]["domain"] == "ai-ref.com"
        assert sources[0]["found_in"] == "AI Overview"
        assert sources[0]["url"] == "https://ai-ref.com/page"  # DataForSEO URL preserved, fake LLM URL ignored
        assert sources[0]["why"] == "Comprehensive overview of AI citability factors."

        # Second is organic
        assert sources[1]["domain"] == "organic-top.org"
        assert sources[1]["found_in"] == "Organic top 10"
        assert sources[1]["url"] == "https://organic-top.org/overview"
        assert sources[1]["why"] == "Benchmark standards for technical architecture."


def test_ai_plan_dataforseo_failure_graceful_fallback():
    """
    Test 5: If DataForSEO fails, plan is still generated, serp_used=False, warning added.
    """
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.SerpClient.fetch_serp_live", side_effect=Exception("DataForSEO 500 error")), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.side_effect = [
            {"query": "fallback search query"},
            {
                "questions_to_answer": [
                    {"question": "How to start?", "draft_answer": "Read chapter 1.", "answer_source": "page"}
                ],
                "suggested_h2_structure": [],
                "data_opportunities": [],
                "paragraphs_to_add": [],
                "inconsistencies": [],
            }
        ]

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://mysite.com/article",
                "title": "Title",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Read chapter 1.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        assert data["serp_used"] is False
        assert any("Google data unavailable for this plan; questions and sources are AI-suggested only." in w for w in data["warnings"])
        assert data["questions_to_answer"][0]["origin"] == "ai"
        assert data["sources_to_cite"] == []


def test_verification_preserves_verify_and_filters_financial_advice():
    """
    Test 6:
    - remove_verification_phrases preserves 'Investors must verify their identity before investing.'
    - remove_financial_advice_phrases strips prohibited sentences.
    """
    from main import remove_verification_phrases, remove_financial_advice_phrases

    # Verification: 'verify' standalone preserved, editorial phrases removed
    text_verify = "Investors must verify their identity before investing. This should be verified by the admin. Please proceed."
    cleaned_v = remove_verification_phrases(text_verify)
    assert "Investors must verify their identity before investing." in cleaned_v
    assert "Please proceed." in cleaned_v
    assert "should be verified" not in cleaned_v

    # Financial advice removal: English
    text_fin_en = "The fund was founded in 2020. Investors should allocate 20% to bonds. It holds AAA assets."
    cleaned_fin_en = remove_financial_advice_phrases(text_fin_en)
    assert "The fund was founded in 2020." in cleaned_fin_en
    assert "It holds AAA assets." in cleaned_fin_en
    assert "Investors should allocate" not in cleaned_fin_en

    # Financial advice removal: Spanish
    text_fin_es = "La empresa reportó beneficios en 2024. Los inversores deberían comprar participaciones ahora. La sede está en Madrid."
    cleaned_fin_es = remove_financial_advice_phrases(text_fin_es)
    assert "La empresa reportó beneficios en 2024." in cleaned_fin_es
    assert "La sede está en Madrid." in cleaned_fin_es
    assert "Los inversores deberían comprar" not in cleaned_fin_es


@pytest.mark.asyncio
async def test_audit_scores_identical_with_and_without_serp():
    """
    Test 7: The audit citability score and all dimension breakdowns are strictly identical
    regardless of whether AI and DataForSEO are enabled or disabled.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Auditing AI Citability Guide</title>
        <meta name="description" content="A comprehensive guide to understanding AI citability." />
    </head>
    <body>
        <article>
            <h1>Auditing AI Citability Guide</h1>
            <p>Artificial intelligence systems cite web pages when content is structured, authoritative, and verified with clear citations and direct data.</p>
            <h2>How AI Search Engines Work</h2>
            <p>Large language models ingest high quality articles to deliver answers to user queries directly in generated summaries.</p>
        </article>
    </body>
    </html>
    """

    # 1. Audit with AI & SERP disabled
    s_disabled = Settings(llm_base_url="", llm_model="", llm_api_key="", dataforseo_login="", dataforseo_password="")
    with patch("src.services.audit_service.get_settings", return_value=s_disabled):
        res_disabled = await client_audit_helper(html_content)

    # 2. Audit with AI & SERP enabled
    s_enabled = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )
    with patch("src.services.audit_service.get_settings", return_value=s_enabled):
        res_enabled = await client_audit_helper(html_content)

    assert res_disabled.total_score == res_enabled.total_score
    assert len(res_disabled.dimensions) == len(res_enabled.dimensions)
    for d1, d2 in zip(res_disabled.dimensions, res_enabled.dimensions):
        assert d1.name == d2.name
        assert d1.score == d2.score
        assert d1.weight == d2.weight
        assert d1.contribution == d2.contribution


async def client_audit_helper(html: str):
    from src.models.schemas import AuditRequest, PageData
    from src.services.audit_service import run_single_audit

    page_data = PageData(
        url="https://example.com/ai-citability",
        final_url="https://example.com/ai-citability",
        html_raw=html,
        html_rendered=html,
        text_content="Auditing AI Citability Guide Artificial intelligence systems cite web pages when content is structured.",
        status_code=200,
        load_time_ms=50.0,
    )
    mock_scraper = MagicMock()
    mock_scraper.scrape = AsyncMock(return_value=page_data)
    semaphore = asyncio.Semaphore(1)

    return await run_single_audit(
        request=AuditRequest(url="https://example.com/ai-citability"),
        scraper=mock_scraper,
        scrape_semaphore=semaphore,
        fetch_robots_fn=AsyncMock(return_value=("User-agent: *\nAllow: /", 200)),
        measure_ttfb_fn=AsyncMock(return_value=(100.0, [100.0])),
    )


# ---------------------------------------------------------------------------
# 18. Access Code Protection & Rate Limiting Tests
# ---------------------------------------------------------------------------

def test_access_code_settings():
    s_default = Settings(access_code="")
    assert s_default.access_required is False
    assert s_default.serp_daily_limit == 100

    s_configured = Settings(
        access_code="super-secret-code",
        dataforseo_password="my-password",
        serp_daily_limit=50,
    )
    assert s_configured.access_required is True
    assert s_configured.serp_daily_limit == 50
    # Ensure secrets are masked in repr
    r = repr(s_configured)
    assert "super-secret-code" not in r
    assert "my-password" not in r


def test_access_code_protection_disabled():
    client = TestClient(app)
    s = Settings(access_code="")
    with patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        r_version = client.get("/api/version")
        assert r_version.status_code == 200
        assert r_version.json()["access_required"] is False

        r_health = client.get("/api/health")
        assert r_health.status_code == 200

        r_check = client.post("/api/auth/check")
        assert r_check.status_code == 200
        assert r_check.json() == {"status": "ok"}


def test_access_code_protection_enabled():
    client = TestClient(app)
    code = "correct-auth-token-123"
    s = Settings(access_code=code)

    with patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        # 1. /api/health and /api/version exempt
        r_health = client.get("/api/health")
        assert r_health.status_code == 200

        r_version = client.get("/api/version")
        assert r_version.status_code == 200
        assert r_version.json()["access_required"] is True
        assert code not in r_version.text

        # 2. Missing access code -> 401 "Access code required"
        r_no_header = client.post("/api/auth/check")
        assert r_no_header.status_code == 401
        assert r_no_header.json()["detail"] == "Access code required"

        # 3. Wrong access code -> 401 "Invalid access code"
        r_wrong = client.post("/api/auth/check", headers={"X-Access-Code": "wrong-code"})
        assert r_wrong.status_code == 401
        assert r_wrong.json()["detail"] == "Invalid access code"

        # 4. Correct access code -> 200
        r_valid = client.post("/api/auth/check", headers={"X-Access-Code": code})
        assert r_valid.status_code == 200
        assert r_valid.json() == {"status": "ok"}

        # 5. Protected endpoints without code return 401
        assert client.post("/api/audit", json={"url": "https://example.com"}).status_code == 401
        assert client.post("/api/batch", json={"urls": ["https://example.com"]}).status_code == 401
        assert client.get("/api/batch/some-job/csv").status_code == 401
        assert client.get("/api/batch/some-job/issues-csv").status_code == 401
        assert client.post("/api/ai/fixes", json={"url": "https://example.com"}).status_code == 401
        assert client.post("/api/ai/plan", json={"url": "https://example.com"}).status_code == 401


def test_access_code_rate_limiting():
    client = TestClient(app)
    code = "vault-pass-999"
    s = Settings(access_code=code)

    with patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        # 10 incorrect attempts -> 401
        for _ in range(10):
            res = client.post("/api/auth/check", headers={"X-Access-Code": "wrong", "X-Forwarded-For": "198.51.100.1"})
            assert res.status_code == 401

        # 11th incorrect attempt -> 401 (len(recent_failures) becomes 11)
        res11 = client.post("/api/auth/check", headers={"X-Access-Code": "wrong", "X-Forwarded-For": "198.51.100.1"})
        assert res11.status_code == 401

        # 12th attempt from same IP -> 429
        res12 = client.post("/api/auth/check", headers={"X-Access-Code": "wrong", "X-Forwarded-For": "198.51.100.1"})
        assert res12.status_code == 429
        assert res12.json()["detail"] == "Too many attempts, try again later"

        # Even with the correct code, blocked during 15-minute window
        res_blocked = client.post("/api/auth/check", headers={"X-Access-Code": code, "X-Forwarded-For": "198.51.100.1"})
        assert res_blocked.status_code == 429

        # A different IP is not blocked
        res_other = client.post("/api/auth/check", headers={"X-Access-Code": code, "X-Forwarded-For": "198.51.100.2"})
        assert res_other.status_code == 200

        # Exempt routes are not blocked
        assert client.get("/api/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
        assert client.get("/api/version", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200


def test_health_check_head_request():
    """Verify that HEAD /api/health responds with 200, empty body, and requires no access code."""
    client = TestClient(app)
    s = Settings(access_code="secret-gate-code")
    with patch("main.settings", s), patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        res = client.head("/api/health")
        assert res.status_code == 200
        assert len(res.content) == 0


def test_access_code_cors_headers():
    client = TestClient(app)
    code = "cors-test-code-123"
    s = Settings(access_code=code)
    allowed_origin = s.cors_origins[1]  # "https://carloscanofernandez.com"

    with patch("main.settings", s), patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        # 1. 401 without code includes CORS header
        r_no_code = client.post("/api/auth/check", headers={"Origin": allowed_origin})
        assert r_no_code.status_code == 401
        assert r_no_code.headers.get("access-control-allow-origin") == allowed_origin
        assert r_no_code.headers.get("access-control-allow-credentials") == "true"

        # 2. 401 with wrong code includes CORS header
        r_wrong_code = client.post(
            "/api/auth/check",
            headers={"X-Access-Code": "bad-code", "Origin": allowed_origin}
        )
        assert r_wrong_code.status_code == 401
        assert r_wrong_code.headers.get("access-control-allow-origin") == allowed_origin

        # 3. 429 rate limit includes CORS header
        for _ in range(11):
            client.post("/api/auth/check", headers={"X-Access-Code": "wrong", "X-Forwarded-For": "203.0.113.50"})
        r_429 = client.post(
            "/api/auth/check",
            headers={"X-Access-Code": "wrong", "X-Forwarded-For": "203.0.113.50", "Origin": allowed_origin}
        )
        assert r_429.status_code == 429
        assert r_429.headers.get("access-control-allow-origin") == allowed_origin

        # 4. Preflight OPTIONS request to /api/audit
        r_options = client.options(
            "/api/audit",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-access-code,content-type",
            }
        )
        assert r_options.status_code == 200
        assert r_options.headers.get("access-control-allow-origin") == allowed_origin
        allowed_headers = r_options.headers.get("access-control-allow-headers", "").lower()
        assert "x-access-code" in allowed_headers or "*" in allowed_headers


def test_cors_origin_regex_headers():
    from main import reset_failed_auth_attempts
    reset_failed_auth_attempts()
    client = TestClient(app)
    code = "cors-regex-secret"
    regex_pattern = r"https://geo-auditor-v2(-[a-z0-9-]+)?\.vercel\.app"
    s = Settings(access_code=code, cors_origin_regex=regex_pattern)

    allowed_vercel_preview = "https://geo-auditor-v2-git-main-abc.vercel.app"
    allowed_vercel_prod = "https://geo-auditor-v2.vercel.app"
    disallowed_origin = "https://otro-sitio.vercel.app"

    with patch("main.settings", s), patch("main.get_settings", return_value=s), patch("config.settings.get_settings", return_value=s):
        # 1. Matching regex origin receives Access-Control-Allow-Origin
        r_preview = client.get("/api/health", headers={"Origin": allowed_vercel_preview})
        assert r_preview.status_code == 200
        assert r_preview.headers.get("access-control-allow-origin") == allowed_vercel_preview

        r_prod = client.get("/api/health", headers={"Origin": allowed_vercel_prod})
        assert r_prod.status_code == 200
        assert r_prod.headers.get("access-control-allow-origin") == allowed_vercel_prod

        # 2. Disallowed origin does NOT receive Access-Control-Allow-Origin
        r_disallowed = client.get("/api/health", headers={"Origin": disallowed_origin})
        assert r_disallowed.status_code == 200
        assert r_disallowed.headers.get("access-control-allow-origin") is None

        # 3. 401 without code includes CORS header for matching origin
        r_401 = client.post("/api/auth/check", headers={"Origin": allowed_vercel_preview})
        assert r_401.status_code == 401
        assert r_401.headers.get("access-control-allow-origin") == allowed_vercel_preview

        # 4. 401 with wrong code includes CORS header for matching origin
        r_wrong = client.post(
            "/api/auth/check",
            headers={"X-Access-Code": "wrong-code", "Origin": allowed_vercel_preview}
        )
        assert r_wrong.status_code == 401
        assert r_wrong.headers.get("access-control-allow-origin") == allowed_vercel_preview

        # 5. 429 rate limit includes CORS header for matching origin
        for _ in range(11):
            client.post("/api/auth/check", headers={"X-Access-Code": "bad", "X-Forwarded-For": "198.51.100.99"})
        r_429 = client.post(
            "/api/auth/check",
            headers={"X-Access-Code": "bad", "X-Forwarded-For": "198.51.100.99", "Origin": allowed_vercel_preview}
        )
        assert r_429.status_code == 429
        assert r_429.headers.get("access-control-allow-origin") == allowed_vercel_preview


# ---------------------------------------------------------------------------
# 19. SERP Daily Limit & Fallback Tests
# ---------------------------------------------------------------------------

def test_serp_daily_limit_tracker():
    from src.services.serp_client import SerpDailyCallTracker, SerpDailyLimitExceededError
    tracker = SerpDailyCallTracker()
    assert tracker.get_count() == 0
    assert tracker.check_and_increment(2) == 1
    assert tracker.check_and_increment(2) == 2
    with pytest.raises(SerpDailyLimitExceededError):
        tracker.check_and_increment(2)


@pytest.mark.asyncio
async def test_plan_serp_daily_limit_exceeded_fallback():
    from src.services.serp_client import SerpDailyLimitExceededError
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
        serp_daily_limit=5,
    )

    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "What is citability?",
                "why_it_matters": "Core concept",
                "answer_source": "page",
                "draft_answer": "Citability is the readiness of content for AI models.",
                "suggested_location": "Under introduction",
            }
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "new_paragraphs": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm, \
         patch("src.services.serp_client.SerpClient.fetch_serp_live", side_effect=SerpDailyLimitExceededError("Daily Google data limit reached, try again tomorrow")):

        mock_llm.return_value = mock_llm_plan

        req_data = {
            "ai_context": {
                "url": "https://example.com/test",
                "title": "Citability Guide",
                "h1": "Citability Guide",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Citability is the readiness of content for AI models. It measures clarity.",
            }
        }
        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["serp_used"] is False
        assert data["serp_paa_found"] == 0
        assert "Daily Google data limit reached; questions and sources are AI-suggested only." in data["warnings"]


# ---------------------------------------------------------------------------
# 20. Plan Adjustments Tests (serp_paa_found, Normalization, Data Opps, Missing Info)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serp_paa_found_and_paa_normalization_matching():
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )

    mock_serp = {
        "organic_results": [{"position": 1, "domain": "source.com", "url": "https://source.com/a", "title": "A"}],
        "people_also_ask": [
            {"question": "¿Cuál es la diferencia entre IA y machine learning?", "url": "https://ex.com/1", "domain": "ex.com"},
            {"question": "¿Cómo auditar una web?", "url": "https://ex.com/2", "domain": "ex.com"},
        ],
        "ai_overview": None,
        "related_searches": [],
        "market": "ES/es",
    }

    # LLM plan returns 2 questions: one matches PAA with missing ¿ and lowercasing, the other is brand new
    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "Cual es la diferencia entre ia y machine learning",
                "why_it_matters": "Distinction needed",
                "answer_source": "page",
                "draft_answer": "AI is broader while ML is a subset.",
                "suggested_location": "Section 2",
            },
            {
                "question": "Cuanto cuesta una auditoria GEO",
                "why_it_matters": "Pricing intent",
                "answer_source": "needs_info",
                "draft_answer": "Depende de la complejidad.",
                "suggested_location": "FAQ",
            },
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "new_paragraphs": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm, \
         patch("src.services.serp_client.SerpClient.fetch_serp_live", new_callable=AsyncMock) as mock_serp_call:

        mock_llm.return_value = mock_llm_plan
        mock_serp_call.return_value = mock_serp

        req_data = {
            "ai_context": {
                "url": "https://example.com/es/test",
                "title": "Machine Learning vs IA",
                "h1": "Machine Learning vs IA",
                "language": "es",
                "content_type": "guide_blog",
                "main_text": "AI is broader while ML is a subset. Guide on machine learning.",
            },
            "target_query": "diferencia entre ia y machine learning",
        }
        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["serp_used"] is True
        assert data["serp_paa_found"] == 2

        q0 = data["questions_to_answer"][0]
        assert q0["origin"] == "google_paa"
        assert q0["question"] == "¿Cuál es la diferencia entre IA y machine learning?"

        q1 = data["questions_to_answer"][1]
        assert q1["origin"] == "ai"


@pytest.mark.asyncio
async def test_plan_discards_technical_data_opportunities():
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_plan = {
        "questions_to_answer": [],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [
            {
                "suggestion": "Implement schema markup for organization",
                "source_type": "Schema generator",
            },
            {
                "suggestion": "Include benchmark for standard latency",
                "source_type": "Annual financial report",
            },
            {
                "suggestion": "Añadir alt text a los diagramas",
                "source_type": "CMS image editor",
            },
            {
                "suggestion": "Optimizar metadata de la página",
                "source_type": "Yoast plugin",
            },
            {
                "suggestion": "Añadir datos estructurados de producto",
                "source_type": "Schema.org",
            },
            {
                "suggestion": "Add survey findings on user retention",
                "source_type": "Product analytics dashboard",
            },
        ],
        "new_paragraphs": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.return_value = mock_llm_plan

        req_data = {
            "ai_context": {
                "url": "https://example.com/test",
                "title": "Product Growth",
                "h1": "Product Growth",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Sample text about product growth and metrics.",
            }
        }
        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()

        opps = data["data_opportunities"]
        # Only 2 non-technical opportunities should remain
        assert len(opps) == 2
        suggestions = [o["suggestion"] for o in opps]
        assert "Include benchmark for standard latency" in suggestions
        assert "Add survey findings on user retention" in suggestions
        for o in opps:
            combined = (o["suggestion"] + " " + o["source_type"]).lower()
            assert "schema" not in combined
            assert "structured data" not in combined
            assert "alt text" not in combined
            assert "metadata" not in combined
            assert "datos estructurados" not in combined


@pytest.mark.asyncio
async def test_plan_reclassifies_page_to_needs_info():
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "What is the launch date?",
                "why_it_matters": "Timeline",
                "answer_source": "page",
                "draft_answer": "Official documentation does not specify the exact launch date of the product.",
                "suggested_location": "Under Section 1",
            },
            {
                "question": "Who conducted the survey?",
                "why_it_matters": "Authority",
                "answer_source": "page",
                "draft_answer": "The study was conducted by Oxford University in October 2023.",
                "suggested_location": "Under Methodology",
            },
            {
                "question": "¿Cuáles son los requisitos de acceso?",
                "why_it_matters": "Onboarding",
                "answer_source": "page",
                "draft_answer": "La convocatoria oficial no menciona los requisitos para solicitar la beca.",
                "suggested_location": "Sección requisitos",
            },
            {
                "question": "¿Cuál es la tasa de éxito?",
                "why_it_matters": "Results",
                "answer_source": "page",
                "draft_answer": "El informe anual no indica el porcentaje final de aprobados.",
                "suggested_location": "Conclusión",
            },
            {
                "question": "What are the supported payment methods?",
                "why_it_matters": "Purchasing",
                "answer_source": "page",
                "draft_answer": "Public pricing does not provide details on payment gateways.",
                "suggested_location": "Pricing FAQ",
            },
            {
                "question": "What is the warranty period?",
                "why_it_matters": "Policy",
                "answer_source": "page",
                "draft_answer": "Warranty coverage is not specified in the documentation.",
                "suggested_location": "Terms",
            },
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "new_paragraphs": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.return_value = mock_llm_plan

        req_data = {
            "ai_context": {
                "url": "https://example.com/test",
                "title": "Study results",
                "h1": "Study results",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Oxford University published a study in October 2023.",
            }
        }
        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()

        questions = data["questions_to_answer"]
        # Question 0: "does not specify" -> reclassified to "needs_info"
        assert questions[0]["answer_source"] == "needs_info"
        # Question 1: valid page answer -> kept as "page"
        assert questions[1]["answer_source"] == "page"
        # Question 2: "no menciona" -> reclassified to "needs_info"
        assert questions[2]["answer_source"] == "needs_info"
        # Question 3: "no indica" -> reclassified to "needs_info"
        assert questions[3]["answer_source"] == "needs_info"
        # Question 4: "does not provide" -> reclassified to "needs_info"
        assert questions[4]["answer_source"] == "needs_info"
        # Question 5: "not specified" -> reclassified to "needs_info"
        assert questions[5]["answer_source"] == "needs_info"


# ---------------------------------------------------------------------------
# strip_page_meta_references tests
# ---------------------------------------------------------------------------

def test_strip_page_meta_references_unit():
    from src.utils.lang_patterns import strip_page_meta_references

    # Empty / none
    assert strip_page_meta_references("") == ""
    assert strip_page_meta_references(None) == ""

    # Required test cases from specification:
    # 1. "Fans can visit the page of each club." -> preserved
    assert strip_page_meta_references("Fans can visit the page of each club.") == "Fans can visit the page of each club."
    # 2. "The page's disclaimer states the token is not available." -> eliminated
    assert strip_page_meta_references("The page's disclaimer states the token is not available.") == ""
    # 3. "Según la página, no hay fecha." -> eliminated
    assert strip_page_meta_references("Según la página, no hay fecha.") == ""

    # Mixed sentence preservation:
    mixed = (
        "Fans can visit the page of each club. "
        "The page's disclaimer states the token is not available. "
        "Club members receive priority booking."
    )
    assert strip_page_meta_references(mixed) == "Fans can visit the page of each club. Club members receive priority booking."

    # English phrases:
    # 'the page states', 'the page says', 'the page mentions', 'the page does not',
    # 'the page's disclaimer', 'this page', 'per the page', 'according to the page', 'on the page'
    en_samples = [
        ("SEO has evolved into generative search optimization. The page states that quality is vital.", "SEO has evolved into generative search optimization."),
        ("The page says users prefer speed. Performance benchmarks are critical.", "Performance benchmarks are critical."),
        ("The page mentions three key tiers. Pricing starts immediately.", "Pricing starts immediately."),
        ("Direct answers rank highest. The page does not detail enterprise plans.", "Direct answers rank highest."),
        ("The page's disclaimer clarifies terms. Real-time updates occur daily.", "Real-time updates occur daily."),
        ("This page explains how to achieve that. Content quality is priority.", "Content quality is priority."),
        ("Per the page, the tool is free. Developers can test it.", "Developers can test it."),
        ("According to the page, results vary. Testing is recommended.", "Testing is recommended."),
        ("Information on the page reflects recent metrics. Citations build authority.", "Citations build authority."),
    ]
    for raw, expected in en_samples:
        assert strip_page_meta_references(raw) == expected

    # Spanish phrases:
    # 'la página indica', 'la página dice', 'según la página', 'esta página'
    es_samples = [
        ("El análisis semántico mejora la visibilidad. La página indica que los datos son de 2023.", "El análisis semántico mejora la visibilidad."),
        ("La página dice que el servicio es gratuito. Las auditorías son semanales.", "Las auditorías son semanales."),
        ("Según la página, no hay fecha. El proyecto comenzará en otoño.", "El proyecto comenzará en otoño."),
        ("En esta página se detallan las opciones. Las fuentes primarias aumentan la confianza.", "Las fuentes primarias aumentan la confianza."),
    ]
    for raw, expected in es_samples:
        assert strip_page_meta_references(raw) == expected

    # Extended English meta references:
    # 'this guide', 'this article', 'this post', 'this text', 'the guide', 'the article', 'the post', 'the text above', 'the text below'
    en_extended_samples = [
        ("This guide does not rank French stadiums by capacity. Marseille is a historic city.", "Marseille is a historic city."),
        ("In this article, we evaluate stadium safety. Fans expect clear protocols.", "Fans expect clear protocols."),
        ("This post highlights the vibrant local atmosphere. Matchday begins hours earlier.", "Matchday begins hours earlier."),
        ("As seen in this text, ticket demands are high. Plan ahead for derby matches.", "Plan ahead for derby matches."),
        ("The guide provides detailed seat layouts. Public transport connects directly.", "Public transport connects directly."),
        ("The article covers fan loyalty programs. Supporters can join official clubs.", "Supporters can join official clubs."),
        ("The post explores tournament history. International matches draw global audiences.", "International matches draw global audiences."),
        ("As stated in the text above, capacity is 67,000. It is among the largest in Europe.", "It is among the largest in Europe."),
        ("Refer to the text below for route options. The stadium is easily accessible.", "The stadium is easily accessible."),
    ]
    for raw, expected in en_extended_samples:
        assert strip_page_meta_references(raw) == expected

    # Extended Spanish meta references:
    # 'esta guía', 'este artículo', 'este texto', 'la guía', 'el artículo'
    es_extended_samples = [
        ("Esta guía no compara la capacidad de los recintos. El Vélodrome es un emblema de Marsella.", "El Vélodrome es un emblema de Marsella."),
        ("En este artículo analizamos la historia del estadio. Los aficionados apoyan al club incondicionalmente.", "Los aficionados apoyan al club incondicionalmente."),
        ("Este texto examina la asistencia a los partidos. La liga francesa tiene gran seguimiento.", "La liga francesa tiene gran seguimiento."),
        ("La guía detalla las zonas de aparcamiento. El metro llega directamente a la entrada.", "El metro llega directamente a la entrada."),
        ("El artículo resume la trayectoria del entrenador. La temporada actual es muy competitiva.", "La temporada actual es muy competitiva."),
    ]
    for raw, expected in es_extended_samples:
        assert strip_page_meta_references(raw) == expected

    # Legitimate non-meta sentences that MUST NOT be stripped:
    legitimate_samples = [
        "A tour guide took the visitors around the stadium.",
        "We mailed the tickets at the post office before noon.",
        "Guiding principles of fair play govern the tournament.",
        "Guidance from coaches improves athlete endurance.",
        "Supporters read article 5 of the club statutes.",
    ]
    for s in legitimate_samples:
        assert strip_page_meta_references(s) == s

    # Text composed entirely of meta-references
    text_all_meta = "This page provides an overview. According to the page, details follow."
    assert strip_page_meta_references(text_all_meta) == ""


def test_ai_plan_strip_meta_references_paragraphs_and_answers():
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_daily_limit=200,
    )

    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "What is the core benefit?",
                "why_it_matters": "Clarity",
                "answer_source": "page",
                "draft_answer": "AI search delivers direct answers to users. This page details all of them.",
                "suggested_location": "Intro",
            },
            {
                "question": "Where can I find pricing?",
                "why_it_matters": "Conversion",
                "answer_source": "page",
                "draft_answer": "This page provides complete pricing tiers.",
                "suggested_location": "Pricing",
            },
            {
                "question": "What are the refund terms?",
                "why_it_matters": "Policy",
                "answer_source": "needs_info",
                "draft_answer": "This page does not state refund terms. Customers are entitled to refunds within [EDITOR: refund window — terms of service].",
                "suggested_location": "Footer FAQ",
            },
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "paragraphs_to_add": [
            {
                "target_issue": "Thin content",
                "suggested_text": "Generative engines index structured information efficiently. The page mentions several key metrics. Real-time evaluation requires automated benchmarking.",
                "placement": "Section 2",
            }
        ],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.return_value = mock_llm_plan

        req_data = {
            "ai_context": {
                "url": "https://example.com/test",
                "title": "AI Search Guide",
                "h1": "AI Search Guide",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "AI search delivers direct answers to users. Generative engines index structured information efficiently. Real-time evaluation requires automated benchmarking.",
            }
        }
        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()

        # Check paragraphs_to_add: "The page mentions..." was stripped out
        paras = data["paragraphs_to_add"]
        assert len(paras) == 1
        assert "The page mentions" not in paras[0]["suggested_text"]
        assert paras[0]["suggested_text"] == "Generative engines index structured information efficiently. Real-time evaluation requires automated benchmarking."

        # Check questions:
        # Question 1 ("What is the core benefit?"): "This page details all of them." stripped out, kept as page answer
        # Question 2 ("Where can I find pricing?"): entire draft_answer was meta-reference, so question was discarded
        # Question 3 ("What are the refund terms?"): meta-reference stripped, publishable part with editor gap preserved
        questions = data["questions_to_answer"]
        assert len(questions) == 2

        q0 = questions[0]
        assert q0["question"] == "What is the core benefit?"
        assert q0["answer_source"] == "page"
        assert q0["draft_answer"] == "AI search delivers direct answers to users."

        q1 = questions[1]
        assert q1["question"] == "What are the refund terms?"
        assert q1["answer_source"] == "needs_info"
        assert "This page does not state refund terms" not in q1["draft_answer"]
        assert "Customers are entitled to refunds within [EDITOR: refund window — terms of service]." in q1["draft_answer"]

        # Discarded question must NOT be in combined_schema (FAQPage)
        if data.get("combined_schema") and data["combined_schema"].get("mainEntity"):
            faq_questions = [item["name"] for item in data["combined_schema"]["mainEntity"]]
            assert "Where can I find pricing?" not in faq_questions
            assert "What is the core benefit?" in faq_questions


def test_ai_fixes_strip_meta_references_in_lead():
    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_daily_limit=200,
    )

    mock_llm_fixes = {
        "json_ld": {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Lead testing headline"
        },
        "lead_paragraph": {
            "suggested": "Enterprise systems require rigorous testing standards. The page's disclaimer states compliance is optional. Security audits must occur on a regular schedule."
        },
    }

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.return_value = mock_llm_fixes

        req_payload = {
            "ai_context": {
                "url": "https://example.com/security",
                "title": "Enterprise Security",
                "h1": "Enterprise Security",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Enterprise systems require rigorous testing standards. Security audits must occur on a regular schedule.",
            }
        }

        resp = client.post("/api/ai/fixes", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        lead_suggested = data["lead_paragraph"]["suggested"]
        assert "The page's disclaimer states compliance is optional." not in lead_suggested
        assert lead_suggested == "Enterprise systems require rigorous testing standards. Security audits must occur on a regular schedule."


# ---------------------------------------------------------------------------
# DataForSEO timeout, retry & caching tests
# ---------------------------------------------------------------------------

def test_serp_timeout_seconds_setting_and_client_usage():
    from src.services.serp_client import SerpClient

    # Default timeout is 90.0s
    default_settings = Settings()
    assert default_settings.serp_timeout_seconds == 90.0

    # Custom timeout configuration
    custom_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login123",
        dataforseo_password="password123",
        serp_timeout_seconds=45.0,
    )
    assert custom_settings.serp_timeout_seconds == 45.0

    client_serp = SerpClient(custom_settings)
    assert client_serp.settings.serp_timeout_seconds == 45.0


@pytest.mark.asyncio
async def test_serp_timeout_retry_success():
    """
    Test that a timeout on attempt 0 retries after 3.0s, succeeds on attempt 1,
    and returns a plan with Google data (serp_used is True).
    """
    from main import ai_plan_cache
    from src.services.serp_client import serp_cache
    ai_plan_cache.clear()
    serp_cache.clear()

    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login123",
        dataforseo_password="password123",
        serp_timeout_seconds=90.0,
    )

    mock_serp_response = {
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "items": [
                            {
                                "type": "people_also_ask",
                                "items": [
                                    {"title": "How to optimize for AI?", "url": "https://industry.org/faq", "domain": "industry.org"}
                                ]
                            },
                            {
                                "type": "organic",
                                "domain": "authority.org",
                                "url": "https://authority.org/guide",
                                "title": "Authoritative Guide"
                            }
                        ]
                    }
                ]
            }
        ]
    }

    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "How to optimize for AI?",
                "why_it_matters": "Core SEO query",
                "answer_source": "page",
                "draft_answer": "AI engines index well structured content.",
                "suggested_location": "FAQ",
            }
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    # Attempt 0: TimeoutException, Attempt 1: 200 OK
    resp_success = MagicMock(status_code=200, json=lambda: mock_serp_response, raise_for_status=lambda: None)

    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm, \
         patch("httpx.AsyncClient.post", side_effect=[httpx.TimeoutException("Read timed out"), resp_success]) as mock_http_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        mock_llm.return_value = mock_llm_plan

        req_data = {
            "ai_context": {
                "url": "https://example.com/guide",
                "title": "AI Optimization",
                "h1": "AI Optimization",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "AI engines index well structured content.",
            },
            "query": "how to optimize for ai",
        }

        resp = client.post("/api/ai/plan", json=req_data)
        assert resp.status_code == 200
        data = resp.json()

        # Both attempts were executed
        assert mock_http_post.call_count == 2
        # The 3-second sleep was called on timeout retry
        mock_sleep.assert_any_call(3.0)

        # Result includes Google data
        assert data["serp_used"] is True
        assert data["serp_paa_found"] >= 1
        assert any(q["origin"] == "google_paa" for q in data["questions_to_answer"])


@pytest.mark.asyncio
async def test_serp_timeout_retry_failure_no_cache_and_retry_next_call():
    """
    Test that timeout on both attempts generates plan without Google data,
    adds warning, does NOT store plan in ai_plan_cache, and allows next call
    to retry DataForSEO.
    """
    from main import ai_plan_cache
    from src.services.serp_client import serp_cache
    ai_plan_cache.clear()
    serp_cache.clear()

    client = TestClient(app)
    s = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login123",
        dataforseo_password="password123",
        serp_timeout_seconds=90.0,
    )

    mock_llm_plan = {
        "questions_to_answer": [
            {
                "question": "What is AI search?",
                "why_it_matters": "Clarity",
                "answer_source": "page",
                "draft_answer": "AI search gives direct answers.",
                "suggested_location": "Intro",
            }
        ],
        "outline_expansion": [],
        "comparison_tables": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
        "sources_to_cite": [],
    }

    req_data = {
        "ai_context": {
            "url": "https://example.com/guide2",
            "title": "AI Optimization Guide",
            "h1": "AI Optimization Guide",
            "language": "en",
            "content_type": "guide_blog",
            "main_text": "AI search gives direct answers.",
        },
        "query": "ai search guide",
    }

    # First call: both attempts time out
    with patch("main.get_settings", return_value=s), \
         patch("config.settings.get_settings", return_value=s), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm, \
         patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")) as mock_http_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_llm.return_value = mock_llm_plan

        resp1 = client.post("/api/ai/plan", json=req_data)
        assert resp1.status_code == 200
        data1 = resp1.json()

        # Both attempts timed out
        assert mock_http_post.call_count == 2
        # Plan was generated without Google data
        assert data1["serp_used"] is False
        assert any("Google data unavailable" in w for w in data1["warnings"])

        # Cache check: plan must NOT be stored in ai_plan_cache
        assert len(ai_plan_cache) == 0

        # Second call: DataForSEO is attempted again because not cached
        resp2 = client.post("/api/ai/plan", json=req_data)
        assert resp2.status_code == 200
        # Call count increased by 2 more attempts
        assert mock_http_post.call_count == 4


@pytest.mark.asyncio
async def test_ai_plan_suggested_lead_and_expanded_schema():
    """
    Test that /api/ai/plan returns suggested_lead with original, suggested, rationale,
    and combined_schema containing description, mainEntityOfPage, about, and mentions.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_return = {
        "suggested_lead": {
            "original": "Old first paragraph without focus.",
            "suggested": "Optimized lead that defines GEO concepts immediately with precision.",
            "rationale": "Clear focus and entity placement in first sentence.",
        },
        "json_ld": {
            "description": "Comprehensive guide on modern GEO optimization strategies.",
            "about": [{"@type": "Thing", "name": "Generative Engine Optimization"}],
            "mentions": [{"@type": "Thing", "name": "Perplexity AI"}],
        },
        "questions_to_answer": [],
        "suggested_h2_structure": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:

        mock_call.return_value = mock_llm_return

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/geo-guide",
                "title": "GEO Optimization Guide",
                "h1": "GEO Optimization Guide",
                "first_paragraph": "Old first paragraph without focus.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old first paragraph without focus. Generative Engine Optimization is key.",
            }
        })
        assert res.status_code == 200
        data = res.json()

        # Check suggested_lead
        assert data["suggested_lead"] is not None
        assert data["suggested_lead"]["original"] == "Old first paragraph without focus."
        assert data["suggested_lead"]["suggested"] == "Optimized lead that defines GEO concepts immediately with precision."
        assert data["suggested_lead"]["rationale"] == "Clear focus and entity placement in first sentence."

        # Check combined_schema has description, mainEntityOfPage, about, mentions
        schema = data["combined_schema"]
        assert "@graph" in schema
        article = next((item for item in schema["@graph"] if item.get("@type") in ("Article", "BlogPosting")), None)
        assert article is not None
        assert article["description"] == "Comprehensive guide on modern GEO optimization strategies."
        assert article["mainEntityOfPage"] == "https://example.com/geo-guide"
        assert len(article["about"]) == 1
        assert article["about"][0]["name"] == "Generative Engine Optimization"
        assert len(article["mentions"]) == 1
        assert article["mentions"][0]["name"] == "Perplexity AI"


@pytest.mark.asyncio
async def test_ai_plan_suggested_lead_unverified_figures_fallback_and_warning():
    """
    Test that an invented figure in suggested_lead of /api/ai/plan causes fallback to original
    lead and adds warning.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_return = {
        "suggested_lead": {
            "suggested": "This guide claims traffic increased by 999 percent in 2026.",
            "rationale": "High impact lead",
        },
        "questions_to_answer": [],
        "suggested_h2_structure": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:

        mock_call.return_value = mock_llm_return

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/traffic-guide",
                "title": "Traffic Guide",
                "first_paragraph": "Original safe opening paragraph without numbers.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Original safe opening paragraph without numbers. General body text.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        assert data["suggested_lead"]["suggested"] == "Original safe opening paragraph without numbers."
        assert "The suggested lead contained figures not found on the page and was discarded." in data["warnings"]


@pytest.mark.asyncio
async def test_ai_plan_suggested_lead_filters_financial_advice_and_meta():
    """
    Test that financial advice and meta-references ('the page') are stripped from suggested_lead in /api/ai/plan.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_return = {
        "suggested_lead": {
            "suggested": "Investors should consider this opportunity. The page explains modern indexing architectures.",
            "rationale": "Direct summary.",
        },
        "questions_to_answer": [],
        "suggested_h2_structure": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_call:

        mock_call.return_value = mock_llm_return

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/indexing",
                "title": "Indexing Guide",
                "first_paragraph": "Old intro paragraph.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old intro paragraph. Modern indexing architectures provide fast search results.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        suggested = data["suggested_lead"]["suggested"]
        assert "investors should" not in suggested.lower()
        assert "the page" not in suggested.lower()


# ---------------------------------------------------------------------------
# Robust JSON Extraction, max_tokens, json-repair, and Retry Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_truncated_json_repaired_by_json_repair():
    """
    Test 1: Truncated JSON that json-repair can fix -> valid plan without failing.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_max_tokens=16000,
    )

    # Incomplete JSON (missing closing braces/brackets)
    truncated_content = (
        '{"questions_to_answer": [{"question": "What is GEO?", "draft_answer": "GEO is AI search optimization.", "answer_source": "page"}], '
        '"suggested_h2_structure": [{"h2": "Understanding GEO", "purpose": "Explains concept.", "status": "new"}], '
        '"data_opportunities": [], "paragraphs_to_add": [], "inconsistencies": []'
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": truncated_content}, "finish_reason": "stop"}]
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/geo",
                "title": "GEO Guide",
                "first_paragraph": "Old intro.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old intro. GEO is AI search optimization.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["questions_to_answer"]) == 1
        assert data["questions_to_answer"][0]["question"] == "What is GEO?"
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_llm_irreparable_json_retries_and_succeeds():
    """
    Test 2: Irreparable JSON on first attempt and valid on retry -> valid plan with exactly one extra call.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_max_tokens=16000,
    )

    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 200
    mock_resp_fail.json.return_value = {
        "choices": [{"message": {"content": "I apologize, but I cannot format this right now."}, "finish_reason": "stop"}]
    }

    valid_content = (
        '{"questions_to_answer": [{"question": "What is SEO?", "draft_answer": "SEO is search optimization.", "answer_source": "page"}], '
        '"suggested_h2_structure": [], "data_opportunities": [], "paragraphs_to_add": [], "inconsistencies": []}'
    )
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.json.return_value = {
        "choices": [{"message": {"content": valid_content}, "finish_reason": "stop"}]
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("httpx.AsyncClient.post", side_effect=[mock_resp_fail, mock_resp_ok]) as mock_post:

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/seo",
                "title": "SEO Guide",
                "first_paragraph": "Old intro.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old intro. SEO is search optimization.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["questions_to_answer"]) == 1
        assert data["questions_to_answer"][0]["question"] == "What is SEO?"
        assert mock_post.call_count == 2

        # Verify retry prompt was appended to user message on second call
        second_call_payload = mock_post.call_args_list[1][1]["json"]
        last_user_msg = [m for m in second_call_payload["messages"] if m["role"] == "user"][-1]
        assert "Your previous answer was cut off or invalid. Return ONLY valid JSON" in last_user_msg["content"]


@pytest.mark.asyncio
async def test_llm_finish_reason_length_triggers_retry():
    """
    Test 3: finish_reason == 'length' triggers retry even if text has some content.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_max_tokens=16000,
    )

    mock_resp_length = MagicMock()
    mock_resp_length.status_code = 200
    mock_resp_length.json.return_value = {
        "choices": [{"message": {"content": '{"partial": "cut off'}, "finish_reason": "length"}]
    }

    valid_content = (
        '{"questions_to_answer": [{"question": "What is AI?", "draft_answer": "AI is artificial intelligence.", "answer_source": "page"}], '
        '"suggested_h2_structure": [], "data_opportunities": [], "paragraphs_to_add": [], "inconsistencies": []}'
    )
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.json.return_value = {
        "choices": [{"message": {"content": valid_content}, "finish_reason": "stop"}]
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("httpx.AsyncClient.post", side_effect=[mock_resp_length, mock_resp_ok]) as mock_post:

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/ai",
                "title": "AI Guide",
                "first_paragraph": "Old intro.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old intro. AI is artificial intelligence.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["questions_to_answer"]) == 1
        assert data["questions_to_answer"][0]["question"] == "What is AI?"
        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_llm_two_consecutive_failures_controlled_error():
    """
    Test 4: Two consecutive failures (initial and retry) -> controlled 502 error.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_max_tokens=16000,
    )

    mock_resp_fail1 = MagicMock()
    mock_resp_fail1.status_code = 200
    mock_resp_fail1.json.return_value = {
        "choices": [{"message": {"content": "Not JSON 1"}, "finish_reason": "stop"}]
    }

    mock_resp_fail2 = MagicMock()
    mock_resp_fail2.status_code = 200
    mock_resp_fail2.json.return_value = {
        "choices": [{"message": {"content": "Not JSON 2"}, "finish_reason": "stop"}]
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("httpx.AsyncClient.post", side_effect=[mock_resp_fail1, mock_resp_fail2]) as mock_post:

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://example.com/fail",
                "title": "Fail Guide",
                "first_paragraph": "Old intro.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Old intro text.",
            }
        })
        assert res.status_code == 502
        assert "Could not extract valid JSON from AI response" in res.json()["detail"]
        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_llm_max_tokens_in_request_payload():
    """
    Test 5: max_tokens present in the request payload sent to the LLM provider.
    """
    client_llm = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        max_tokens=16000,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"test": true}'}, "finish_reason": "stop"}]
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        res = await client_llm.call_chat_completion([{"role": "user", "content": "hello"}])
        assert res == {"test": True}
        assert mock_post.call_count == 1
        payload = mock_post.call_args[1]["json"]
        assert "max_tokens" in payload
        assert payload["max_tokens"] == 16000


def test_is_excluded_source_domains_and_patterns():
    """
    Test candidate source exclusion list:
    - Image and video banks (shutterstock, istockphoto, gettyimages, dreamstime, alamy, depositphotos, 123rf, stock.adobe.com, pond5, pexels, unsplash, pinterest)
    - Google domains (google.*, maps.google.*, support.google.*)
    - Shops (amazon.*, ebay.*, etsy.*, aliexpress.*)
    - Social networks
    - Titles containing "stock photo", "stock video", "stock footage"
    - URLs with /stock-photo, /stock-video, or /photos/ on image domains
    - Legitimate sources (wikipedia.org, stadium websites, etc.) are NOT excluded.
    """
    from src.services.serp_client import is_excluded_source

    page_dom = "socios.com"

    # Audited page itself
    assert is_excluded_source("socios.com", page_domain=page_dom) is True
    assert is_excluded_source("www.socios.com", page_domain=page_dom) is True
    assert is_excluded_source("blog.socios.com", page_domain=page_dom) is True

    # Image and video banks
    assert is_excluded_source("dreamstime.com", page_domain=page_dom) is True
    assert is_excluded_source("istockphoto.com", "https://www.istockphoto.com/photo/velodrome", page_domain=page_dom) is True
    assert is_excluded_source("shutterstock.com", page_domain=page_dom) is True
    assert is_excluded_source("gettyimages.com", page_domain=page_dom) is True
    assert is_excluded_source("alamy.com", page_domain=page_dom) is True
    assert is_excluded_source("depositphotos.com", page_domain=page_dom) is True
    assert is_excluded_source("123rf.com", page_domain=page_dom) is True
    assert is_excluded_source("stock.adobe.com", page_domain=page_dom) is True
    assert is_excluded_source("pond5.com", page_domain=page_dom) is True
    assert is_excluded_source("pexels.com", page_domain=page_dom) is True
    assert is_excluded_source("unsplash.com", page_domain=page_dom) is True
    assert is_excluded_source("pinterest.com", page_domain=page_dom) is True

    # Google domains
    assert is_excluded_source("google.com", page_domain=page_dom) is True
    assert is_excluded_source("maps.google.es", page_domain=page_dom) is True
    assert is_excluded_source("support.google.com", page_domain=page_dom) is True
    assert is_excluded_source("google.co.uk", page_domain=page_dom) is True

    # Shops
    assert is_excluded_source("amazon.com", page_domain=page_dom) is True
    assert is_excluded_source("amazon.es", "https://www.amazon.es/dp/123", page_domain=page_dom) is True
    assert is_excluded_source("ebay.com", page_domain=page_dom) is True
    assert is_excluded_source("etsy.com", page_domain=page_dom) is True
    assert is_excluded_source("aliexpress.com", page_domain=page_dom) is True

    # Social networks
    assert is_excluded_source("facebook.com", page_domain=page_dom) is True
    assert is_excluded_source("x.com", page_domain=page_dom) is True
    assert is_excluded_source("instagram.com", page_domain=page_dom) is True

    # Stock titles
    assert is_excluded_source("stadium-news.com", title="CEPAC Velodrome - stock photo collection", page_domain=page_dom) is True
    assert is_excluded_source("stadium-news.com", title="Marseille fans - stock footage 4K", page_domain=page_dom) is True
    assert is_excluded_source("stadium-news.com", title="Stadium celebration - stock video", page_domain=page_dom) is True

    # URL path filters
    assert is_excluded_source("any-domain.com", url="https://any-domain.com/stock-photo/123", page_domain=page_dom) is True
    assert is_excluded_source("any-domain.com", url="https://any-domain.com/stock-video/123", page_domain=page_dom) is True
    assert is_excluded_source("photo-press.com", url="https://photo-press.com/photos/marseille", page_domain=page_dom) is True

    # Legitimate non-excluded sources
    assert is_excluded_source("en.wikipedia.org", "https://en.wikipedia.org/wiki/Stade_V%C3%A9lodrome", title="Stade Velodrome", page_domain=page_dom) is False
    assert is_excluded_source("stadevelodrome.com", "https://www.stadevelodrome.com/visite", title="Official Stadium Site", page_domain=page_dom) is False
    assert is_excluded_source("lemonde.fr", "https://www.lemonde.fr/sport/article/marseille", title="Le Monde Sport", page_domain=page_dom) is False


def test_sources_to_cite_filters_out_why_null_or_empty():
    """
    Test AI relevance filter for candidate sources:
    - Sources with why: null or empty are discarded.
    - Sources with why text are kept.
    - If all sources are discarded, sources_to_cite is empty.
    """
    from main import app, ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        dataforseo_login="login1",
        dataforseo_password="pw1",
    )

    mock_serp = {
        "market": "FR/fr",
        "people_also_ask": [],
        "related_searches": [],
        "ai_overview_sources": [
            {"domain": "source-good.com", "url": "https://source-good.com/info", "title": "Good Source"},
            {"domain": "source-bad.com", "url": "https://source-bad.com/junk", "title": "Irrelevant Directory"},
        ],
        "organic": [
            {"domain": "source-empty.com", "url": "https://source-empty.com/blank", "title": "Blank Why"},
        ],
    }

    mock_llm_plan = {
        "questions_to_answer": [
            {"question": "What is the capacity?", "draft_answer": "The capacity is 67,000 spectators.", "answer_source": "page"}
        ],
        "suggested_h2_structure": [],
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
        "sources_why": [
            {"index": 1, "why": "Authoritative guide on stadium capacity and historical renovations."},
            {"index": 2, "why": None},  # AI marks as unsuitable (why: null)
            {"index": 3, "why": ""},    # AI returns empty string
        ]
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("main.settings", mock_settings), \
         patch("src.services.llm_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.get_settings", return_value=mock_settings), \
         patch("src.services.serp_client.SerpClient.fetch_serp_live", new_callable=AsyncMock, return_value=mock_serp), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_llm.side_effect = [
            {"query": "velodrome stadium"},
            mock_llm_plan,
        ]

        res = client.post("/api/ai/plan", json={
            "ai_context": {
                "url": "https://www.socios.com/cepac-velodrome-olympique-de-marseille-stadium/",
                "title": "CEPAC Velodrome",
                "first_paragraph": "Olympique de Marseille play at the CEPAC Velodrome.",
                "language": "en",
                "content_type": "guide_blog",
                "main_text": "Olympique de Marseille play at the CEPAC Velodrome with capacity of 67,000.",
            }
        })
        assert res.status_code == 200
        data = res.json()
        sources = data["sources_to_cite"]

        # Only source 1 is retained, source 2 (why: None) and source 3 (why: "") are discarded
        assert len(sources) == 1
        assert sources[0]["domain"] == "source-good.com"
        assert sources[0]["url"] == "https://source-good.com/info"
        assert sources[0]["why"] == "Authoritative guide on stadium capacity and historical renovations."


# ---------------------------------------------------------------------------
# 30. LLM Streaming & 524 Handling Tests
# ---------------------------------------------------------------------------

class MockAsyncIteratorStream(httpx.AsyncByteStream):
    def __init__(self, chunks: List[bytes]):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_llm_streaming_multi_chunk_valid_json():
    """
    Test 1: SSE response in multiple fragments forming valid JSON yields correct parsed result.
    """
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=True,
    )

    d1 = {"choices": [{"delta": {"content": '{"result": '}, "finish_reason": None}]}
    d2 = {"choices": [{"delta": {"content": '"success", '}, "finish_reason": None}]}
    d3 = {"choices": [{"delta": {"content": '"score": 100}'}, "finish_reason": "stop"}]}

    raw_stream = (
        f"data: {json.dumps(d1)}\n\n"
        f"data: {json.dumps(d2)}\n\n"
        f"data: {json.dumps(d3)}\n\n"
        f"data: [DONE]\n\n"
    ).encode("utf-8")

    resp_stream = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=MockAsyncIteratorStream([raw_stream]),
    )

    with patch("httpx.AsyncClient.send", return_value=resp_stream) as mock_send:
        res = await client.call_chat_completion([{"role": "user", "content": "hello"}])
        assert res == {"result": "success", "score": 100}
        assert mock_send.call_count == 1
        req = mock_send.call_args[0][0]
        payload = json.loads(req.content.decode("utf-8"))
        assert payload.get("stream") is True


@pytest.mark.asyncio
async def test_llm_streaming_finish_reason_length_triggers_retry():
    """
    Test 2: SSE response with finish_reason 'length' triggers automatic retry.
    """
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=True,
    )

    d_len = {"choices": [{"delta": {"content": '{"partial": true'}, "finish_reason": "length"}]}
    raw_stream_len = f"data: {json.dumps(d_len)}\n\ndata: [DONE]\n\n".encode("utf-8")
    resp_length = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=MockAsyncIteratorStream([raw_stream_len]),
    )

    d_ok = {"choices": [{"delta": {"content": '{"complete": true}'}, "finish_reason": "stop"}]}
    raw_stream_ok = f"data: {json.dumps(d_ok)}\n\ndata: [DONE]\n\n".encode("utf-8")
    resp_ok = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=MockAsyncIteratorStream([raw_stream_ok]),
    )

    with patch("httpx.AsyncClient.send", side_effect=[resp_length, resp_ok]) as mock_send:
        res = await client.call_chat_completion([{"role": "user", "content": "test length"}])
        assert res == {"complete": True}
        assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_llm_streaming_fallback_when_gateway_returns_plain_json():
    """
    Test 3: Gateway returns plain application/json even though stream=True was requested -> processed normally.
    """
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=True,
    )

    resp_json = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"choices": [{"message": {"content": '{"fallback": "json"}'}, "finish_reason": "stop"}]},
    )

    with patch("httpx.AsyncClient.send", return_value=resp_json) as mock_send:
        res = await client.call_chat_completion([{"role": "user", "content": "fallback test"}])
        assert res == {"fallback": "json"}


@pytest.mark.asyncio
async def test_llm_streaming_disabled_setting_omits_stream():
    """
    Test 4: When llm_streaming=False, the request payload does not have stream: True.
    """
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=False,
    )

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"choices": [{"message": {"content": '{"no_stream": true}'}, "finish_reason": "stop"}]},
    )

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        res = await client.call_chat_completion([{"role": "user", "content": "no stream"}])
        assert res == {"no_stream": True}
        assert mock_post.call_count == 1
        payload = mock_post.call_args[1]["json"]
        assert "stream" not in payload


@pytest.mark.asyncio
async def test_llm_524_error_message_clarity():
    """
    Test 5: 524 status from Cloudflare yields user-friendly message and no retry in non-streaming mode.
    """
    # Non-streaming 524
    client_non_stream = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=False,
    )
    mock_resp_524 = httpx.Response(524, text="Cloudflare 524 A timeout occurred")

    with patch("httpx.AsyncClient.post", return_value=mock_resp_524) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(LLMClientError) as exc_info:
            await client_non_stream.call_chat_completion([{"role": "user", "content": "timeout test"}])
        assert "The AI service took too long to respond. Please try again." in str(exc_info.value)
        # Verify 524 was not retried in non-streaming mode
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()

    # Streaming 524
    client_stream = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="secret-key",
        daily_limit=10,
        streaming=True,
    )
    with patch("httpx.AsyncClient.send", return_value=mock_resp_524):
        with pytest.raises(LLMClientError) as exc_info_stream:
            await client_stream.call_chat_completion([{"role": "user", "content": "timeout stream"}])

def test_normalize_heading_and_deterministic_present_matching():
    from main import normalize_heading

    # Test normalization mechanics
    assert normalize_heading("What Is the CEPAC Vélodrome?") == "what is the cepac velodrome"
    assert normalize_heading("  CEPAC Vélodrome: History! ") == "cepac velodrome history"
    assert normalize_heading("CEPAC Vélodrome FAQs?") == "cepac velodrome faqs"

    page_h2s = [
        "What Is the CEPAC Vélodrome?",
        "CEPAC Vélodrome History",
        "CEPAC Vélodrome and Marseille Supporters",
        "CEPAC Vélodrome and Fan Engagement",
        "CEPAC Vélodrome FAQs",
    ]
    norm_page = [normalize_heading(h) for h in page_h2s]

    # Matching cases (different casing, accent variations, punctuation, spaces)
    assert normalize_heading("what is the cepac velodrome") in norm_page
    assert normalize_heading("What is the CEPAC Velodrome?") in norm_page
    assert normalize_heading("CEPAC Velodrome History") in norm_page
    assert normalize_heading("CEPAC Vélodrome & Marseille Supporters") not in norm_page  # '&' vs 'and' -> correctly not matching
    assert normalize_heading("CEPAC Vélodrome FAQs") in norm_page

    # Case that MUST NOT match (distinct topic)
    assert normalize_heading("How to Buy Tickets for Vélodrome") not in norm_page
    assert normalize_heading("New Stadium Expansion") not in norm_page


def test_editor_gap_survives_all_filters():
    from main import strip_urls, all_numbers_in_page, normalize_text_for_numbers
    import json_repair

    page_text = "The CEPAC Vélodrome in Marseille has 67,000 seats and opened in 1937."
    page_norm = normalize_text_for_numbers(page_text)

    # 1. Draft answer with [EDITOR: ...] containing description and source
    draft = (
        "The largest stadium in France is [EDITOR: stadium name and capacity — official stadium records]. "
        "The CEPAC Vélodrome, with 67,000 seats, is one of the country's most iconic football grounds."
    )

    # Filter: all_numbers_in_page should ignore numbers inside [EDITOR: ...] and check numbers outside
    assert all_numbers_in_page(draft, page_norm) is True

    # Even if [EDITOR: ...] contains numbers not in the page (e.g. 80,000), it must survive
    draft_with_number_in_gap = "Largest venue is [EDITOR: 80,000 capacity venue — UEFA report]. Marseille has 67,000 seats."
    assert all_numbers_in_page(draft_with_number_in_gap, page_norm) is True

    # But numbers outside gap not in page must still fail
    draft_with_invented_outside = "Paris venue has 85,000 seats. Marseille has 67,000 seats."
    assert all_numbers_in_page(draft_with_invented_outside, page_norm) is False

    # Filter: strip_urls preserves [EDITOR: ...]
    text_with_url_in_gap = "See [EDITOR: data at https://example.org — UEFA] and https://strip-me.com now."
    cleaned = strip_urls(text_with_url_in_gap)
    assert "[EDITOR: data at https://example.org — UEFA]" in cleaned
    assert "https://strip-me.com" not in cleaned

    # Filter: json_repair preserves [EDITOR: ...]
    json_blob = f'{{"draft_answer": "{draft}"}}'
    repaired = json_repair.loads(json_blob)
    assert "[EDITOR: stadium name and capacity — official stadium records]" in repaired["draft_answer"]


def test_ai_plan_h2_status_deterministic_present():
    """Test that /api/ai/plan deterministically marks matching H2s as 'present' even if LLM said 'existing' or 'new'."""
    from main import app, ai_plan_cache
    ai_plan_cache.clear()
    client = TestClient(app)

    mock_llm_result = {
        "suggested_lead": {
            "original": "Original text.",
            "suggested": "Direct answer opening paragraph.",
            "rationale": "Clear focus.",
        },
        "json_ld": {"description": "Test", "about": [], "mentions": []},
        "questions_to_answer": [
            {
                "question": "What is the largest stadium in France?",
                "draft_answer": "The largest stadium in France is [EDITOR: stadium name and capacity — official stadium records]. The CEPAC Vélodrome has 67,000 seats.",
                "answer_source": "needs_info",
            }
        ],
        "suggested_h2_structure": [
            {"h2": "What Is the CEPAC Vélodrome?", "purpose": "Explains the stadium overview.", "status": "existing"},
            {"h2": "CEPAC Velodrome History", "purpose": "Details origins and milestones.", "status": "new"},
            {"h2": "A Brand New Future Section", "purpose": "Future prospects.", "status": "new"},
        ],
        "suggested_table": None,
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": [],
    }

    req = {
        "ai_context": {
            "url": "https://www.socios.com/cepac-velodrome-olympique-de-marseille-stadium/",
            "language": "en",
            "content_type": "guide_blog",
            "main_text": "The CEPAC Vélodrome has 67,000 seats.",
            "existing_h2s": [
                "What Is the CEPAC Vélodrome?",
                "CEPAC Vélodrome History",
                "CEPAC Vélodrome and Marseille Supporters",
            ],
            "failing_submetrics": [],
        }
    }

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_llm_result
        res = client.post("/api/ai/plan", json=req)
    assert res.status_code == 200
    data = res.json()

    h2_items = data["suggested_h2_structure"]
    assert len(h2_items) == 3

    # "What Is the CEPAC Vélodrome?" exactly matches page H2 -> must be 'present'
    assert h2_items[0]["h2"] == "What Is the CEPAC Vélodrome?"
    assert h2_items[0]["status"] == "present"

    # "CEPAC Velodrome History" matches "CEPAC Vélodrome History" with accent normalization -> must be 'present'
    assert h2_items[1]["h2"] == "CEPAC Velodrome History"
    assert h2_items[1]["status"] == "present"

    # "A Brand New Future Section" is NOT on page -> remains 'new'
    assert h2_items[2]["h2"] == "A Brand New Future Section"
    assert h2_items[2]["status"] == "new"

    # Question with [EDITOR: ...] needs_info is retained with gap intact
    q0 = data["questions_to_answer"][0]
    assert q0["answer_source"] == "needs_info"
    assert "[EDITOR: stadium name and capacity — official stadium records]" in q0["draft_answer"]


def test_needs_info_meta_reference_and_empty_editor_gaps_discarded():
    """
    Test that needs_info answers starting with meta-commentary like 'This guide does not...'
    are filtered, and questions leaving no substantive publishable sentence are discarded.
    """
    from main import ai_plan_cache
    ai_plan_cache.clear()

    client = TestClient(app)
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    mock_llm_result = {
        "questions_to_answer": [
            {
                # Starts with "This guide does not..." and has no publishable sentence left
                "question": "What is the ranking of stadiums in France?",
                "draft_answer": "This guide does not rank French stadiums. [EDITOR: national stadium rankings — ministry of sports].",
                "answer_source": "needs_info"
            },
            {
                # Has a meta-reference sentence AND a valid publishable sentence with an editor gap
                "question": "What is the largest arena?",
                "draft_answer": "This article does not specify the largest arena. The Stade Vélodrome holds thousands of fans while the national record belongs to [EDITOR: largest arena name and capacity — national sports authority].",
                "answer_source": "needs_info"
            },
            {
                # Only has editor gap, no publishable text at all
                "question": "Who designed the roof?",
                "draft_answer": "[EDITOR: architect name and firm — official records].",
                "answer_source": "needs_info"
            }
        ],
        "suggested_h2_structure": [],
        "suggested_table": None,
        "data_opportunities": [],
        "paragraphs_to_add": [],
        "inconsistencies": []
    }

    req = {
        "ai_context": {
            "url": "https://www.socios.com/cepac-velodrome-olympique-de-marseille-stadium/",
            "title": "CEPAC Vélodrome Guide",
            "first_paragraph": "The CEPAC Vélodrome is located in Marseille.",
            "main_text": "The CEPAC Vélodrome is located in Marseille. The Stade Vélodrome holds thousands of fans.",
            "language": "en",
            "content_type": "guide_blog",
        },
        "query": "CEPAC stadium"
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_llm_result
        res = client.post("/api/ai/plan", json=req)

    assert res.status_code == 200
    data = res.json()
    questions = data["questions_to_answer"]
    # Only Question 2 should survive: Question 1 was completely stripped of publishable text; Question 3 had only a gap
    assert len(questions) == 1
    assert questions[0]["question"] == "What is the largest arena?"
    assert "This article does not" not in questions[0]["draft_answer"]
    assert "Stade Vélodrome holds thousands" in questions[0]["draft_answer"]
    assert "[EDITOR: largest arena name and capacity — national sports authority]" in questions[0]["draft_answer"]


def test_markdown_to_html_conversion_and_elements():
    """Verify markdown library converts headings, tables, and lists correctly."""
    import markdown
    md = """# Main Title
An introductory paragraph with information.

## Overview
What is this stadium?

| Year | Capacity |
|---|---|
| 1937 | 35,000 |
| 2026 | 67,000 |

- Item 1
- Item 2
"""
    html = markdown.markdown(md, extensions=['tables', 'fenced_code'])
    assert "<h1>Main Title</h1>" in html
    assert "<h2>Overview</h2>" in html
    assert "<table>" in html
    assert "<th>Capacity</th>" in html
    assert "<td>67,000</td>" in html
    assert "<ul>" in html
    assert "<li>Item 1</li>" in html


def test_content_html_audits_headings_and_tables_and_preserves_content_text():
    """
    Test that AuditRequest with content_html correctly audits H2 and tables without scraping,
    while content_text continues to work unchanged.
    """
    client = TestClient(app)

    # 1. Test content_html detects H2, tables, lists
    rich_html = """
    <article>
        <h1>Complete Guide to Football Arenas</h1>
        <p>This guide provides comprehensive facts, seating capacities, and transport details for modern football arenas.</p>
        <h2>What is the stadium history?</h2>
        <p>The stadium was built in 1937 and serves as the primary home ground for the local club in Ligue 1.</p>
        <table>
            <thead><tr><th>Year</th><th>Capacity</th></tr></thead>
            <tbody><tr><td>1937</td><td>35,000</td></tr><tr><td>2026</td><td>67,000</td></tr></tbody>
        </table>
        <ul>
            <li>Metro Line 2</li>
            <li>Bus line 21</li>
        </ul>
    </article>
    """
    res_html = client.post("/api/audit", json={"content_html": rich_html})
    assert res_html.status_code == 200
    data_html = res_html.json()
    assert data_html["total_score"] > 0
    # Verify aeo_structure detected headers
    aeo_dim = next((d for d in data_html["dimensions"] if d["name"] == "aeo_structure"), None)
    assert aeo_dim is not None
    assert aeo_dim["score"] > 0

    # 2. Test content_text continues to function as before
    plain_text = "This is a simple plain text article about sports stadiums with sufficient length to test."
    res_text = client.post("/api/audit", json={"content_text": plain_text})
    assert res_text.status_code == 200
    data_text = res_text.json()
    assert data_text["total_score"] > 0


def test_rewrite_marks_unverified_figures_and_keeps_existing():
    """Test that numbers not present in original page or plan get flagged with [EDITOR: verify this figure ...]."""
    from main import rewrite_article
    from src.models.schemas import AIRewriteRequest, AIContext, AIPlanResponse

    req = AIRewriteRequest(
        ai_context=AIContext(
            main_text="The stadium was built in 1937 and holds 67,000 spectators.",
            language="en"
        ),
        ai_plan=AIPlanResponse(
            combined_schema={},
            warnings=[]
        )
    )

    mock_llm_markdown = """# Stadium Guide
The stadium holds 67,000 spectators and had an attendance record of 99,999 in recent years.
"""

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (mock_llm_markdown, "stop")
        res = client.post("/api/ai/rewrite", json=req.model_dump())

    assert res.status_code == 200
    data = res.json()
    draft = data["draft_markdown"]
    warnings = data["warnings"]
    assert "67,000" in draft
    assert "[EDITOR: verify this figure (99,999) — not in the original page]" in draft
    assert any("99,999" in w for w in warnings)


def test_rewrite_restores_missing_sensitive_legal_phrases():
    """Test that missing legal/risk disclaimers from original text are restored verbatim."""
    req = {
        "ai_context": {
            "main_text": "The club fan tokens allow voting on team polls. Risk warning: Crypto assets are volatile and your capital is at risk. Not financial advice.",
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }

    mock_llm_markdown = """# Fan Token Guide
Fan tokens allow voting on official team polls and accessing club rewards.
"""

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (mock_llm_markdown, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    data = res.json()
    draft = data["draft_markdown"]
    warnings = data["warnings"]
    assert "Risk warning: Crypto assets are volatile and your capital is at risk." in draft or "capital is at risk" in draft
    assert "Not financial advice" in draft
    assert any("Restored required sensitive legal disclaimer" in w for w in warnings)


def test_rewrite_preserves_editor_gaps_across_filters():
    """Test that [EDITOR: ...] placeholders survive strip_urls and strip_page_meta_references."""
    req = {
        "ai_context": {
            "main_text": "Marseille stadium information.",
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }

    mock_llm_markdown = """# Marseille Guide
This guide details all stadium info https://example.com/stadium.
The official architect was [EDITOR: architect name — municipal archives].
"""

    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )

    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (mock_llm_markdown, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    data = res.json()
    draft = data["draft_markdown"]
    assert "https://example.com/stadium" not in draft
    assert "This guide" not in draft
    assert "[EDITOR: architect name — municipal archives]" in draft


def test_rewrite_score_excludes_same_dimensions_both_sides():
    """Test that /api/ai/rewrite/score excludes technical_infrastructure, metadata_schema, freshness."""
    client = TestClient(app)
    orig_html = """
    <article>
        <h1>Original Guide</h1>
        <p>Short paragraph about the arena in France.</p>
    </article>
    """
    draft_md = """# Improved Guide
An extensive detailed opening paragraph explaining the history, architecture, and matchday experience of the arena.

## Matchday Logistics
Visitors can reach the stadium using public transit.

| Metro | Line |
|---|---|
| Marseille Metro | Line 2 |

- Gate A
- Gate B
"""

    req = {
        "original_html": orig_html,
        "draft_markdown": draft_md,
        "target_query": "stadium guide"
    }

    res = client.post("/api/ai/rewrite/score", json=req)
    assert res.status_code == 200
    data = res.json()
    assert "total_score_before" in data
    assert "total_score_after" in data
    assert "difference" in data
    assert "excluded_dimensions" in data

    excluded = data["excluded_dimensions"]
    assert "technical_infrastructure" in excluded
    assert "metadata_schema" in excluded
    assert "freshness" in excluded

    # Dimension comparison items must only contain content dimensions
    dim_names = [d["name"] for d in data["dimensions"]]
    assert "technical_infrastructure" not in dim_names
    assert "metadata_schema" not in dim_names
    assert "freshness" not in dim_names
    assert "aeo_structure" in dim_names
    assert "format_citability" in dim_names


def test_rewrite_docx_export_endpoint():
    """Test downloading the rewrite draft .docx."""
    client = TestClient(app)
    req = {
        "url": "https://www.socios.com/stadium",
        "draft_markdown": "# Title\n\nContent paragraph with [EDITOR: fact — source].\n\n| H1 | H2 |\n|---|---|\n| A | B |\n",
        "warnings": ["Unverified figure detected (123)"],
        "score_comparison": {
            "total_score_before": 60.0,
            "total_score_after": 82.5,
            "difference": 22.5,
            "dimensions": [
                {
                    "name": "aeo_structure",
                    "score_before": 50.0,
                    "score_after": 90.0,
                    "difference": 40.0
                }
            ],
            "excluded_dimensions": ["technical_infrastructure", "metadata_schema", "freshness"]
        }
    }
    res = client.post("/api/export/rewrite", json=req)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert "rewrite-socios.com-" in res.headers["content-disposition"]
    assert len(res.content) > 1000


# ---------------------------------------------------------------------------
# Original link preservation in /api/ai/rewrite
# ---------------------------------------------------------------------------

_LINKS_MAIN_HTML = """
<article>
  <h1>Stadium Guide</h1>
  <p>Read the <a href="/stadium-history/">stadium history</a> and the
     <a href="https://www.UEFA.com/news/arena/">UEFA report</a>.</p>
  <p>See also <a href="https://uefa.com/news/arena#top">UEFA report again</a>,
     <a href="mailto:press@club.com">press</a> and <a href="#toc">top</a>.</p>
</article>
"""


def test_extract_original_links_relative_absolute_and_dedup():
    from main import extract_original_links
    links = extract_original_links(_LINKS_MAIN_HTML, "https://club.com/guide/")
    urls = [l["url"] for l in links]
    assert urls == ["https://club.com/stadium-history/", "https://www.UEFA.com/news/arena/"]
    assert links[0]["text"] == "stadium history"
    assert links[1]["text"] == "UEFA report"
    assert extract_original_links("", "https://club.com/") == []


def test_filter_draft_urls_keeps_original_removes_invented():
    from main import filter_draft_urls, normalize_link_url
    allowed = {normalize_link_url("https://www.uefa.com/news/arena/")}
    kept = filter_draft_urls("See the [UEFA report](https://uefa.com/news/arena) now.", allowed)
    assert "[UEFA report](https://uefa.com/news/arena)" in kept
    invented = filter_draft_urls("See [fake source](https://invented.example/x) and https://other.example/y.", allowed)
    assert "invented.example" not in invented
    assert "other.example" not in invented
    assert "fake source" in invented


def _rewrite_settings():
    return Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )


def test_rewrite_keeps_original_links_strips_invented_and_warns_missing():
    req = {
        "ai_context": {
            "url": "https://club.com/guide/",
            "main_text": "Read the stadium history and the UEFA report.",
            "main_html": _LINKS_MAIN_HTML,
            "language": "en",
        },
        "ai_plan": {"combined_schema": {}, "warnings": []},
    }
    mock_llm_markdown = (
        "# Stadium Guide\n"
        "Read the [UEFA report](https://uefa.com/news/arena/) and "
        "[a made-up source](https://invented.example/page).\n"
    )
    client = TestClient(app)
    with patch("main.get_settings", return_value=_rewrite_settings()), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (mock_llm_markdown, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    data = res.json()
    draft = data["draft_markdown"]
    assert "[UEFA report](https://uefa.com/news/arena/)" in draft
    assert "invented.example" not in draft
    assert "a made-up source" in draft
    # The missing original link is reported, not force-inserted
    assert "Original link not preserved: stadium history (https://club.com/stadium-history/)" in data["warnings"]
    assert "club.com/stadium-history" not in draft
    # The preserved link is not reported
    assert not any("UEFA report" in w and "not preserved" in w for w in data["warnings"])

    # The prompt sent to the model contains the ORIGINAL LINKS list
    sent = mock_stream.call_args[0][3]["messages"][1]["content"]
    assert "ORIGINAL LINKS" in sent
    assert "[stadium history](https://club.com/stadium-history/)" in sent


def test_rewrite_without_main_html_has_no_link_warnings():
    req = {
        "ai_context": {"main_text": "Plain pasted text about a stadium.", "language": "en"},
        "ai_plan": {"combined_schema": {}, "warnings": []},
    }
    client = TestClient(app)
    with patch("main.get_settings", return_value=_rewrite_settings()), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = ("# Title\nSee [x](https://invented.example/a).\n", "stop")
        res = client.post("/api/ai/rewrite", json=req)
    assert res.status_code == 200
    data = res.json()
    assert "invented.example" not in data["draft_markdown"]
    assert not any("Original link not preserved" in w for w in data["warnings"])


def test_rewrite_score_links_verifiability_not_lower_with_same_links():
    client = TestClient(app)
    orig_html = (
        "<article><h1>Stadium Guide</h1>"
        "<p>The arena opened in 1937 and is described by "
        '<a href="https://www.uefa.com/news/arena/">UEFA</a> and '
        '<a href="https://www.fifa.com/stadiums/">FIFA</a> in their official reports.</p>'
        "</article>"
    )
    draft_md = (
        "# Stadium Guide\n\n"
        "The arena opened in 1937 and is described by "
        "[UEFA](https://www.uefa.com/news/arena/) and "
        "[FIFA](https://www.fifa.com/stadiums/) in their official reports.\n"
    )
    res = client.post("/api/ai/rewrite/score", json={"original_html": orig_html, "draft_markdown": draft_md})
    assert res.status_code == 200
    dim = next(d for d in res.json()["dimensions"] if d["name"] == "links_verifiability")
    assert dim["score_after"] >= dim["score_before"]


def test_rewrite_docx_contains_real_hyperlinks():
    import io, docx as _docx
    from src.utils.docx_brief import generate_rewrite_draft_docx
    data = generate_rewrite_draft_docx(
        url="https://club.com/guide/",
        draft_markdown="# T\n\nRead the [UEFA report](https://uefa.com/news/arena/) now.\n",
        warnings=[],
        score_comparison=None,
    )
    d = _docx.Document(io.BytesIO(data))
    targets = [r.target_ref for r in d.part.rels.values() if r.is_external]
    assert "https://uefa.com/news/arena/" in targets
    body_text = "\n".join(p.text for p in d.paragraphs)
    assert "[UEFA report]" not in body_text
    assert "UEFA report" in body_text


def test_sanitize_pasted_html_google_docs():
    from src.utils.text_processing import sanitize_pasted_html
    raw_docs = (
        '<b id="docs-internal-guid-abcdef12-3456">'
        '<h1>Main Title</h1>'
        '<p style="color: red;" class="c1">First paragraph of text.</p>'
        '<h2>Subheading</h2>'
        '<p>Second paragraph with <a href="https://example.com/source">link</a>.</p>'
        '</b>'
    )
    cleaned = sanitize_pasted_html(raw_docs)
    assert "docs-internal-guid" not in cleaned
    assert "<h1>Main Title</h1>" in cleaned
    assert "<h2>Subheading</h2>" in cleaned
    assert '<a href="https://example.com/source">link</a>' in cleaned
    assert "style=" not in cleaned
    assert "class=" not in cleaned


def test_sanitize_pasted_html_word_headings():
    from src.utils.text_processing import sanitize_pasted_html
    raw_word = (
        '<p class="MsoTitle">Document Title</p>'
        '<p class="MsoNormal">Introductory text from Microsoft Word.</p>'
        '<p class="MsoHeading2">Section Heading</p>'
        '<p class="MsoNormal">More detailed content.</p>'
    )
    cleaned = sanitize_pasted_html(raw_word)
    assert "<h1>Document Title</h1>" in cleaned
    assert "<h2>Section Heading</h2>" in cleaned
    assert "<p>Introductory text from Microsoft Word.</p>" in cleaned
    assert "Mso" not in cleaned


def test_sanitize_pasted_html_security_and_h1_fallback():
    from src.utils.text_processing import sanitize_pasted_html
    dirty = (
        '<script>alert("xss")</script>'
        '<style>body { background: red; }</style>'
        '<p><a href="javascript:alert(1)">bad link</a> and <a href="https://safe.com">good link</a></p>'
        '<!-- HTML comment -->'
        '<h2>Promoted Heading</h2>'
        '<p>Paragraph content.</p>'
    )
    cleaned = sanitize_pasted_html(dirty)
    assert "script" not in cleaned
    assert "style" not in cleaned
    assert "javascript:" not in cleaned
    assert "comment" not in cleaned
    assert "<h1>Promoted Heading</h1>" in cleaned
    assert "Analysis" not in cleaned
    assert '<a href="https://safe.com">good link</a>' in cleaned


def test_audit_markdown_and_plain_content_text():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    with patch("src.services.audit_service.get_settings", return_value=_rewrite_settings()):
        # 1. Markdown in content_text
        md_content = "# Guide Title\n\nIntro text.\n\n## Section One\n\n- Point A\n- Point B\n\n| H1 | H2 |\n|---|---|\n| V1 | V2 |\n"
        res_md = client.post("/api/audit", json={"content_text": md_content})
        assert res_md.status_code == 200
        data_md = res_md.json()
        assert data_md["ai_context"]["h1"] == "Guide Title"
        assert data_md["ai_context"]["h1"] != "Analysis"
        assert "Section One" in data_md["ai_context"]["main_html"]

        # 2. Plain text in content_text
        plain_content = "Plain Article Title\n\nFirst substantive paragraph.\n\nSecond substantive paragraph."
        res_plain = client.post("/api/audit", json={"content_text": plain_content})
        assert res_plain.status_code == 200
        data_plain = res_plain.json()
        assert data_plain["ai_context"]["h1"] == "Plain Article Title"
        assert data_plain["ai_context"]["h1"] != "Analysis"


def test_extract_original_images():
    from main import extract_original_images
    html = (
        '<article>'
        '<img src="https://example.com/hero.jpg" alt="Hero Banner" width="800" height="400" />'
        '<img src="/relative/diagram.png" alt="Architecture" />'
        '<img src="data:image/png;base64,iVBORw0KGgo..." alt="Data URI" />'
        '<img src="https://tracking.com/pixel.gif" alt="" width="1" height="1" />'
        '<img src="https://example.com/icon-16.png" alt="Icon" />'
        '</article>'
    )
    images = extract_original_images(html, base_url="https://example.com")
    assert len(images) == 2
    assert images[0] == {"alt": "Hero Banner", "src": "https://example.com/hero.jpg"}
    assert images[1] == {"alt": "Architecture", "src": "https://example.com/relative/diagram.png"}


def test_filter_draft_urls_with_images_and_links():
    from main import filter_draft_urls, normalize_link_url
    allowed = {
        normalize_link_url("https://example.com/image.png"),
        normalize_link_url("https://example.com/link"),
    }
    line1 = "See ![Hero Chart](https://example.com/image.png) and read [Guide](https://example.com/link)."
    line2 = "Unknown ![Bad Image](https://bad.com/img.png) and unknown [Bad Link](https://bad.com/page)."

    filtered1 = filter_draft_urls(line1, allowed)
    filtered2 = filter_draft_urls(line2, allowed)

    assert "https://example.com/image.png" in filtered1
    assert "https://example.com/link" in filtered1
    assert "https://bad.com" not in filtered2
    assert "Bad Link" in filtered2


def test_rewrite_score_excludes_eeat_authority():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    orig_html = "<h1>Guide</h1><p>Content text about soccer.</p>"
    draft_md = "# Guide\n\nContent text about soccer with expansions."

    res = client.post("/api/ai/rewrite/score", json={"original_html": orig_html, "draft_markdown": draft_md})
    assert res.status_code == 200
    data = res.json()
    assert "eeat_authority" in data["excluded_dimensions"]
    assert "technical_infrastructure" in data["excluded_dimensions"]
    assert "metadata_schema" in data["excluded_dimensions"]
    assert "freshness" in data["excluded_dimensions"]
    dim_names = [d["name"] for d in data["dimensions"]]
    assert "eeat_authority" not in dim_names


def test_rewrite_missing_original_image_warning():
    from fastapi.testclient import TestClient
    from main import app
    req = {
        "ai_context": {
            "url": "https://club.com/guide/",
            "main_text": "Guide with images.",
            "main_html": '<article><p>Text</p><img src="https://club.com/stadium.jpg" alt="Stadium Photo" /></article>',
            "language": "en",
        },
        "ai_plan": {"combined_schema": {}, "warnings": []},
    }
    client = TestClient(app)
    with patch("main.get_settings", return_value=_rewrite_settings()), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        # LLM omits the image
        mock_stream.return_value = ("# Stadium Guide\n\nGuide content without image.\n", "stop")
        res = client.post("/api/ai/rewrite", json=req)
    assert res.status_code == 200
    data = res.json()
    assert any("Original image not preserved: Stadium Photo (https://club.com/stadium.jpg)" in w for w in data["warnings"])


def test_rewrite_docx_renders_images_and_note():
    import io, docx as _docx
    from src.utils.docx_brief import generate_rewrite_draft_docx
    from src.models.schemas import AIRewriteScoreResponse, DimensionScoreComparison
    score_comp = AIRewriteScoreResponse(
        total_score_before=85.0,
        total_score_after=90.0,
        difference=5.0,
        dimensions=[
            DimensionScoreComparison(name="content_depth", score_before=80.0, score_after=90.0, difference=10.0),
        ],
        excluded_dimensions=["technical_infrastructure", "metadata_schema", "freshness", "eeat_authority"],
    )
    data = generate_rewrite_draft_docx(
        url="https://club.com/guide/",
        draft_markdown="# Guide\n\n![Stadium Chart](https://invalid-host-for-testing.local/chart.png)\n\nParagraph.",
        warnings=["Test warning"],
        score_comparison=score_comp,
    )
    d = _docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Content-only comparison: technical, metadata, freshness and authority dimensions are not included." in text
    assert "[Image: Stadium Chart — https://invalid-host-for-testing.local/chart.png]" in text


def test_safe_image_rejects_ssrf_hosts():
    from unittest.mock import patch, MagicMock
    from src.utils.docx_brief import _is_host_safe, _download_safe_image

    bad_hosts = ["127.0.0.1", "10.0.0.1", "10.1.2.3", "169.254.169.254", "localhost", "sub.localhost", "app.local", "internal.corp.internal"]
    for host in bad_hosts:
        assert _is_host_safe(host) is False
        assert _download_safe_image(f"http://{host}/image.png") is None
        assert _download_safe_image(f"https://{host}/image.png") is None

    # Test SSRF via redirect to private IP
    mock_redirect_resp = MagicMock()
    mock_redirect_resp.status_code = 302
    mock_redirect_resp.headers = {"location": "http://169.254.169.254/latest/meta-data"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.stream.return_value.__enter__.return_value = mock_redirect_resp

    with patch("src.utils.docx_brief._is_host_safe", side_effect=lambda h: h == "example.com"), \
         patch("httpx.Client", return_value=mock_client):
        res = _download_safe_image("https://example.com/redirect-to-ssrf.png")
        assert res is None


def test_safe_image_rejects_non_image_content_type():
    from unittest.mock import patch, MagicMock
    from src.utils.docx_brief import _download_safe_image

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.iter_bytes.return_value = [b"<html>not an image</html>"]

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.stream.return_value.__enter__.return_value = mock_resp

    with patch("src.utils.docx_brief._is_host_safe", return_value=True), \
         patch("httpx.Client", return_value=mock_client):
        res = _download_safe_image("https://example.com/not-an-image")
        assert res is None


def test_safe_image_aborts_on_response_exceeding_max_bytes():
    from unittest.mock import patch, MagicMock
    from src.utils.docx_brief import _download_safe_image

    # 1. Content-Length header > 5 MB
    mock_resp_header = MagicMock()
    mock_resp_header.status_code = 200
    mock_resp_header.headers = {
        "content-type": "image/png",
        "content-length": str(6 * 1024 * 1024)
    }
    mock_resp_header.iter_bytes.return_value = []

    mock_client_header = MagicMock()
    mock_client_header.__enter__.return_value = mock_client_header
    mock_client_header.stream.return_value.__enter__.return_value = mock_resp_header

    with patch("src.utils.docx_brief._is_host_safe", return_value=True), \
         patch("httpx.Client", return_value=mock_client_header):
        res = _download_safe_image("https://example.com/huge.png")
        assert res is None

    # 2. Streaming chunks exceeding 5 MB
    mock_resp_stream = MagicMock()
    mock_resp_stream.status_code = 200
    mock_resp_stream.headers = {"content-type": "image/png"}
    # Emit 6 chunks of 1MB each
    chunk_1mb = b"A" * (1024 * 1024)
    mock_resp_stream.iter_bytes.return_value = [chunk_1mb] * 6

    mock_client_stream = MagicMock()
    mock_client_stream.__enter__.return_value = mock_client_stream
    mock_client_stream.stream.return_value.__enter__.return_value = mock_resp_stream

    with patch("src.utils.docx_brief._is_host_safe", return_value=True), \
         patch("httpx.Client", return_value=mock_client_stream):
        res = _download_safe_image("https://example.com/huge-stream.png")
        assert res is None


def test_docx_rewrite_respects_max_15_images():
    import io, base64, docx as _docx
    from unittest.mock import patch
    from src.utils.docx_brief import generate_rewrite_draft_docx

    # 1x1 valid PNG
    b64_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    dummy_png = base64.b64decode(b64_png)

    markdown_lines = ["# Document with many images\n"]
    for idx in range(1, 18):
        markdown_lines.append(f"![Image {idx}](https://example.com/img{idx}.png)\n")
    draft_md = "\n".join(markdown_lines)

    call_count = 0
    def mock_download(url, **kwargs):
        nonlocal call_count
        call_count += 1
        return dummy_png

    with patch("src.utils.docx_brief._download_safe_image", side_effect=mock_download):
        docx_bytes = generate_rewrite_draft_docx(
            url="https://example.com/article",
            draft_markdown=draft_md,
            warnings=[],
        )

    # _download_safe_image should be called at most 15 times
    assert call_count == 15

    doc = _docx.Document(io.BytesIO(docx_bytes))
    all_text = "\n".join(p.text for p in doc.paragraphs)

    # Images 1 through 15 are inserted (as figures)
    assert "Figure: Image 1" in all_text
    assert "Figure: Image 15" in all_text

    # Images 16 and 17 fall back to text [Image: Image 16 — ...]
    assert "[Image: Image 16 — https://example.com/img16.png]" in all_text
    assert "[Image: Image 17 — https://example.com/img17.png]" in all_text


def test_rewrite_empty_content_retries_and_returns_502():
    """Test that empty content triggers 1 retry and then returns 502 with clear message."""
    req = {
        "ai_context": {
            "main_text": "Here is an original article with about twenty words to test the rewrite retry mechanism thoroughly in our test suite.",
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.side_effect = [("", "stop"), ("", "stop")]
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 502
    assert "The AI returned an empty or incomplete draft (finish reason: stop). Please try again." in res.json()["detail"]
    assert mock_stream.call_count == 2


def test_rewrite_empty_first_attempt_then_succeeds_without_false_link_warnings():
    """Test that if attempt 1 is empty, retry succeeds without generating false missing link warnings."""
    req = {
        "ai_context": {
            "url": "https://example.com/stadium",
            "main_html": '<p>Visit <a href="https://example.com/tickets">tickets</a> for details.</p>',
            "main_text": "Visit tickets for details about matchday attendance and seating.",
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    valid_draft = "# Stadium Guide\nVisit [tickets](https://example.com/tickets) for details about matchday attendance and seating."
    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.side_effect = [("", "stop"), (valid_draft, "stop")]
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    assert mock_stream.call_count == 2
    data = res.json()
    assert not any("Original link not preserved" in w for w in data["warnings"])
    assert "https://example.com/tickets" in data["draft_markdown"]


def test_rewrite_finish_reason_length_over_50_percent_success_with_warning():
    """Test that finish_reason 'length' with >50% words retries once and returns draft with length warning."""
    orig_words = "Word " * 50  # 50 words
    req = {
        "ai_context": {
            "main_text": orig_words,
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    draft_35_words = "# Title\n" + ("Word " * 35)  # 36 words, >50% of 50
    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.side_effect = [(draft_35_words, "length"), (draft_35_words, "length")]
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    assert mock_stream.call_count == 2
    data = res.json()
    assert "The draft may be incomplete: the AI reached its length limit. Check the end of the article." in data["warnings"]


def test_rewrite_under_50_percent_twice_returns_502():
    """Test that draft under 50% words on both attempts returns 502 with clear message."""
    orig_text = "Word " * 100  # 100 words
    req = {
        "ai_context": {
            "main_text": orig_text,
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    short_draft = "# Title\nJust ten words here that are way below fifty percent."
    client = TestClient(app)
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.side_effect = [(short_draft, "stop"), (short_draft, "stop")]
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 502
    assert "The AI returned an empty or incomplete draft (finish reason: stop). Please try again." in res.json()["detail"]
    assert mock_stream.call_count == 2


def test_rewrite_settings_applied_only_to_rewrite():
    """Test that GEO_AUDITOR_LLM_REWRITE_MODEL and GEO_AUDITOR_LLM_REWRITE_MAX_TOKENS apply only to /api/ai/rewrite."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
        llm_max_tokens=16000,
        llm_rewrite_model="custom-rewrite-model",
        llm_rewrite_max_tokens=28000,
    )
    client = TestClient(app)

    # 1. Check /api/ai/rewrite uses custom-rewrite-model and 28000
    rewrite_req = {
        "ai_context": {
            "main_text": "A brief article about testing configurations and settings.",
            "language": "en"
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": []
        }
    }
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = ("# Config Test\nA brief article about testing configurations and settings.", "stop")
        res = client.post("/api/ai/rewrite", json=rewrite_req)
        assert res.status_code == 200
        assert mock_stream.call_count == 1
        passed_payload = mock_stream.call_args[0][3]
        assert passed_payload["model"] == "custom-rewrite-model"
        assert passed_payload["max_tokens"] == 28000

    # 2. Check /api/ai/plan does NOT use custom-rewrite-model or 28000
    plan_req = {
        "ai_context": {
            "url": "https://example.com/test",
            "title": "Test Title",
            "h1": "Test H1",
            "language": "en",
            "content_type": "article",
            "main_text": "Some text to analyze for planning purposes.",
        }
    }
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm_plan:
        mock_llm_plan.return_value = {
            "suggested_lead": {"suggested": "Lead"},
            "questions_to_answer": [],
            "suggested_h2_structure": [],
            "paragraphs_to_add": [],
            "sources_to_cite": [],
            "data_opportunities": [],
            "combined_schema": {},
        }
        res_plan = client.post("/api/ai/plan", json=plan_req)
        assert res_plan.status_code == 200
        assert mock_settings.llm_model == "gpt-4o"
        assert mock_settings.llm_max_tokens == 16000


# ---------------------------------------------------------------------------
# Rewrite Quality & Editorial Integrity Tests
# ---------------------------------------------------------------------------

def test_heading_rename_status():
    """Test heading status 'rename' when suggested heading overlaps >=60% with an existing heading on the page."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)
    plan_req = {
        "ai_context": {
            "url": "https://example.com/palermo",
            "title": "Palermo FC Stadium",
            "h1": "Stadio Renzo Barbera",
            "language": "en",
            "existing_h2s": [
                "Future of Stadio Renzo Barbera",
                "History and Architecture",
            ],
            "main_text": "Future of Stadio Renzo Barbera. The venue is being renovated for future European tournaments.",
        }
    }
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient.call_chat_completion", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "suggested_lead": {"suggested": "Palermo stadium guide."},
            "questions_to_answer": [],
            "suggested_h2_structure": [
                # 1. Exact match -> 'present'
                {"h2": "History and Architecture", "purpose": "Overview of history", "status": "existing"},
                # 2. Overlapping match -> 'rename'
                {"h2": "Future of Stadio Renzo Barbera: Renovation and EURO 2032", "purpose": "Details on upcoming upgrades", "status": "new"},
                # 3. Brand new heading -> 'new'
                {"h2": "Transportation and Parking Options", "purpose": "Logistics for visitors", "status": "new"},
            ],
            "paragraphs_to_add": [],
            "sources_to_cite": [],
            "data_opportunities": [],
            "combined_schema": {},
        }
        res = client.post("/api/ai/plan", json=plan_req)

    assert res.status_code == 200
    h2s = res.json()["suggested_h2_structure"]
    assert h2s[0]["status"] == "present"
    assert h2s[1]["status"] == "rename"
    assert h2s[2]["status"] == "new"


def test_duplicate_paragraphs_warning_in_rewrite():
    """Test that paragraphs sharing >= 45% content words trigger a duplicate content warning on real Palermo pairs."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)

    # Real Palermo duplicate pair (a): history name changes
    p_hist1 = (
        "Three name changes mark the ground's history. It opened on January 24, 1932 as the Stadio Littorio, "
        "became the Stadio La Favorita in 1945 after the historic park created by King Ferdinand IV of Bourbon, "
        "and took the name Stadio Renzo Barbera in 2002 following the death of the club's former chairman."
    )
    p_hist2 = (
        "The Stadio Renzo Barbera was opened on January 24, 1932, although it was originally known as Stadio Littorio. "
        "In 1945, the name changed to Stadio La Favorita, after the nearby historic park created by King Ferdinand IV of Bourbon. "
        "In 2002, the stadium changed its name once again, becoming the Stadio Renzo Barbera in honour of Palermo's former club president (1970-80)."
    )

    # Real Palermo duplicate pair (b): stands organization
    p_stands1 = (
        "While the Curva Nord is home to the most vocal Palermo supporters, Curva Sud is partly allocated to away fans. "
        "Tribuna Copertura is the main western grandstand, while Tribuna Montepellegrino is situated opposite the main stand."
    )
    p_stands2 = (
        "Matchdays at the Renzo Barbera are organised around four main sections. The Curva Nord houses the most vocal Palermo "
        "supporters, while the Curva Sud is partly allocated to away fans. Tribuna Copertura is the main western grandstand, "
        "and Tribuna Montepellegrino sits opposite the main stand, facing the mountain that rises behind the city."
    )

    # Real Palermo non-duplicate paragraph (c): music venue
    p_music = (
        "The ground has also served as a music venue. Concerts staged during the 1970s and 1980s brought artists "
        "including Aretha Franklin, Frank Sinatra, Miles Davis, Frank Zappa, Duran Duran and Black Sabbath to Palermo, "
        "drawing tens of thousands of spectators to the stadium across those years."
    )

    req = {
        "ai_context": {
            "main_text": "The historic stadium in Palermo was built in 1932.",
            "language": "en",
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": [],
        }
    }

    # Case 1: Draft with pair (a) -> MUST warn
    draft_a = f"# Title\n\n{p_hist1}\n\n{p_hist2}\n\n## FAQ\n\n### When was it built?\nIt was built in 1932."
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_a, "stop")
        res_a = client.post("/api/ai/rewrite", json=req)
    assert res_a.status_code == 200
    assert any("Possible duplicated content:" in w for w in res_a.json()["warnings"])

    # Case 2: Draft with pair (b) -> MUST warn
    draft_b = f"# Title\n\n{p_stands1}\n\n{p_stands2}\n\n## FAQ\n\n### When was it built?\nIt was built in 1932."
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_b, "stop")
        res_b = client.post("/api/ai/rewrite", json=req)
    assert res_b.status_code == 200
    assert any("Possible duplicated content:" in w for w in res_b.json()["warnings"])

    # Real Palermo duplicate pair (c): intro / key facts
    p_intro1 = (
        "Stadio Renzo Barbera is the historic home stadium of Palermo FC situated in Sicily with an official capacity "
        "of 36,365 seats and opened in 1932 for professional championship football matches."
    )
    p_intro2 = (
        "Located in Sicily, the Stadio Renzo Barbera serves as the home ground of Palermo FC, boasting a capacity "
        "of 36,365 seats since it was inaugurated in 1932 as the primary football arena."
    )

    # Case 3: Draft with pair (c) -> MUST warn
    draft_c = f"# Title\n\n{p_intro1}\n\n{p_intro2}\n\n## FAQ\n\n### When was it built?\nIt was built in 1932."
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_c, "stop")
        res_c = client.post("/api/ai/rewrite", json=req)
    assert res_c.status_code == 200
    assert any("Possible duplicated content:" in w for w in res_c.json()["warnings"])

    # Case 4: Draft with non-duplicate (history vs music) -> MUST NOT warn
    draft_non_dupe = f"# Title\n\n{p_hist1}\n\n{p_music}\n\n## FAQ\n\n### When was it built?\nIt was built in 1932."
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_non_dupe, "stop")
        res_non = client.post("/api/ai/rewrite", json=req)
    assert res_non.status_code == 200
    assert not any("Possible duplicated content:" in w for w in res_non.json()["warnings"])

    # Case 5: CTA button vs paragraphs with URLs -> MUST NOT warn
    btn_cta = "[CHECK HERE FOR PALERMO FC FAN TOKEN® UPDATES](https://www.socios.com/palermo-fan-token/)"
    p_chair = "Renzo Barbera spent a decade as the chairman of [Palermo FC](https://www.socios.com/palermo-fc-history-rivalries-and-football-culture/) during a period of growth for the Sicilian club."
    p_token = "The stadium is not the only place where Palermo fans show their support. Digital experiences provide additional ways for the Rosanero faithful to engage with the club, and the [Palermo FC Fan Token™](https://www.socios.com/socios-com-partners-with-palermo-fc/) is just one example of this type of digital fan engagement."
    draft_cta = f"# Title\n\n{btn_cta}\n\n{p_chair}\n\n{p_token}\n\n## FAQ\n\n### When was it built?\nIt was built in 1932."
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_cta, "stop")
        res_cta = client.post("/api/ai/rewrite", json=req)
    assert res_cta.status_code == 200
    assert not any("Possible duplicated content:" in w for w in res_cta.json()["warnings"])


def test_missing_original_figures_warning():
    """Test warning when figures present in original text are missing from the draft."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)

    # Original has figures 36,365 and 1932
    orig_text = "Stadio Renzo Barbera has a total capacity of 36,365 seats and was inaugurated in 1932."
    # Draft includes 1932 but omits 36,365
    draft_text = "# Stadio Renzo Barbera\n\nThe venue was inaugurated in 1932 as a primary sports arena."

    req = {
        "ai_context": {
            "main_text": orig_text,
            "language": "en",
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": [],
        }
    }

    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_text, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    warnings = res.json()["warnings"]
    assert "Original figure missing from draft: 36,365" in warnings


def test_inconsistency_resolved_vs_unresolved():
    """Test that leaving both conflicting values triggers a warning (including typographic quotes), while resolving it does not."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)

    # Real Palermo pair with typographic curly quote ’ in plan vs ASCII quote ' in draft
    req = {
        "ai_context": {
            "main_text": "Palermo’s former club president (1970-80). Former club chairman between 1970 and 1980.",
            "language": "en",
        },
        "ai_plan": {
            "combined_schema": {},
            "inconsistencies": [
                {
                    "issue": "President vs Chairman inconsistency",
                    "values": ["Palermo’s former club president (1970-80)", "Former club chairman between 1970 and 1980"],
                    "suggestion": "Unify to club president"
                }
            ],
            "warnings": [],
        }
    }

    # Case 1: Unresolved (draft uses ASCII quote ' for president, but both values are present)
    draft_unresolved = (
        "# Palermo FC\n\n"
        "The venue honours Palermo's former club president (1970-80).\n\n"
        "Earlier notes referenced the former club chairman between 1970 and 1980."
    )
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_unresolved, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    assert "Inconsistency not resolved: President vs Chairman inconsistency" in res.json()["warnings"]

    # Case 2: Resolved (only president value present)
    draft_resolved = (
        "# Palermo FC\n\n"
        "The venue honours Palermo's former club president (1970-80) exclusively."
    )
    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_resolved, "stop")
        res2 = client.post("/api/ai/rewrite", json=req)

    assert res2.status_code == 200
    assert not any("Inconsistency not resolved" in w for w in res2.json()["warnings"])


def test_extract_original_faq_real_palermo():
    """Test extract_original_faq extracts all 7 questions from the real Palermo FC HTML FAQ structure."""
    from main import extract_original_faq

    html = """
    <h2>Frequently Asked Questions</h2>
    <ul>
      <li>Where does Palermo FC play? At the Stadio Renzo Barbera.</li>
      <li>What is the capacity of Stadio Renzo Barbera? It holds 36,365.</li>
      <li>When did the Stadio Renzo Barbera open? In 1932.</li>
      <li>Why was it called La Favorita? After the park.</li>
      <li>When was it renamed Renzo Barbera? In 2002.</li>
      <li>Who is Renzo Barbera? Club president.</li>
      <li>Has Palermo stadium hosted World Cup matches? Yes, 1990.</li>
    </ul>
    """
    faq_h2, qs = extract_original_faq(html, "")
    assert faq_h2 == "Frequently Asked Questions"
    assert len(qs) == 7
    expected = [
        "Where does Palermo FC play?",
        "What is the capacity of Stadio Renzo Barbera?",
        "When did the Stadio Renzo Barbera open?",
        "Why was it called La Favorita?",
        "When was it renamed Renzo Barbera?",
        "Who is Renzo Barbera?",
        "Has Palermo stadium hosted World Cup matches?",
    ]
    assert qs == expected

    # Also test main_text fallback with questions
    text = """
    ## Frequently Asked Questions
    - Where does Palermo FC play? At the Stadio Renzo Barbera.
    - What is the capacity of Stadio Renzo Barbera? It holds 36,365.
    - When did the Stadio Renzo Barbera open? In 1932.
    """
    faq_h2_txt, qs_txt = extract_original_faq("", text)
    assert faq_h2_txt == "Frequently Asked Questions"
    assert len(qs_txt) == 3
    assert qs_txt[0] == "Where does Palermo FC play?"


def test_original_faq_preserved_and_editor_gap_warning():
    """Test that original FAQ questions are checked for presence, and editor gaps in FAQ trigger warnings."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)

    orig_text = """Stadio Renzo Barbera is an iconic stadium.

## Frequently Asked Questions

### What is the capacity of the stadium?
The stadium has 36,365 seats.

### When did the stadium open?
It opened in 1932.
"""

    req = {
        "ai_context": {
            "main_text": orig_text,
            "language": "en",
        },
        "ai_plan": {
            "combined_schema": {},
            "warnings": [],
        }
    }

    # Draft keeps question 1, drops question 2, and adds question 3 with an editor gap
    draft_text = """# Stadio Renzo Barbera

The stadium opened in 1932 and accommodates 36,365 supporters.

## Frequently Asked Questions

### What is the capacity of the stadium?
The stadium has 36,365 seats.

### What is the ownership structure?
Palermo FC is owned by [EDITOR: owner name and stake — official records].
"""

    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_text, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    warnings = res.json()["warnings"]

    # 1. Dropped question warning
    assert "Original FAQ question dropped: When did the stadium open?" in warnings
    # 2. FAQ with editor gap warning
    assert "FAQ with editor gap: What is the ownership structure? — fill it or remove it before publishing" in warnings


def test_sources_to_cite_filtering_and_fan_token_restriction():
    """Test that allowed sources_to_cite (max 3 with why) are preserved, invented URLs stripped, and external links in Fan Token stripped."""
    mock_settings = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-test",
    )
    client = TestClient(app)

    req = {
        "ai_context": {
            "main_text": "Original text about football.",
            "main_html": '<a href="https://www.socios.com/palermo">Socios</a>',
            "url": "https://www.socios.com/palermo-article",
            "language": "en",
        },
        "ai_plan": {
            "combined_schema": {},
            "sources_to_cite": [
                {
                    "url": "https://legaseriea.it/stadium",
                    "title": "Lega Serie A",
                    "domain": "legaseriea.it",
                    "found_in": "Organic top 10",
                    "why": "Official league stadium data",
                },
                {
                    "url": "https://palermofc.com/stadium",
                    "title": "Palermo FC",
                    "domain": "palermofc.com",
                    "found_in": "Organic top 10",
                    "why": "Club official guide",
                },
                {
                    "url": "https://uefa.com/venues",
                    "title": "UEFA",
                    "domain": "uefa.com",
                    "found_in": "Organic top 10",
                    "why": "Tournament guidelines",
                },
                {
                    "url": "https://fourth-source.com/stadium",
                    "title": "Fourth Source",
                    "domain": "fourth-source.com",
                    "found_in": "Organic top 10",
                    "why": "Extra fourth source",
                },
            ],
            "warnings": [],
        }
    }

    draft_text = """# Stadio Renzo Barbera

Official match schedules are published by [Lega Serie A](https://legaseriea.it/stadium).
Visitors should check the [Club Guide](https://palermofc.com/stadium).
Rumors were reported on an [Invented Blog](https://invented-rumor-site.com/post).
Fourth source test: [Fourth Source](https://fourth-source.com/stadium).

## Support Palermo Beyond the Matchday

The stadium is not the only place where Palermo fans show their support. Digital experiences provide additional ways for the Rosanero faithful to engage with the club, and the Palermo FC Fan Token™ is just one example of this type of digital fan engagement on [Socios](https://www.socios.com/palermo). See tournament info at [UEFA](https://uefa.com/venues).
"""

    with patch("main.get_settings", return_value=mock_settings), \
         patch("src.services.llm_client.LLMClient._stream_and_extract_content", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = (draft_text, "stop")
        res = client.post("/api/ai/rewrite", json=req)

    assert res.status_code == 200
    data = res.json()
    draft = data["draft_markdown"]
    warnings = data["warnings"]

    # 1. Allowed external sources 1 and 2 preserved
    assert "[Lega Serie A](https://legaseriea.it/stadium)" in draft
    assert "[Club Guide](https://palermofc.com/stadium)" in draft
    assert "External source added: legaseriea.it — check that it supports the claim next to it" in warnings
    assert "External source added: palermofc.com — check that it supports the claim next to it" in warnings

    # 2. Invented URL stripped to anchor text
    assert "https://invented-rumor-site.com/post" not in draft
    assert "Invented Blog" in draft

    # 3. Fourth source exceeds max 3 limit -> stripped
    assert "https://fourth-source.com/stadium" not in draft
    assert "Fourth Source" in draft

    # 4. In Fan Token paragraph: UEFA external link stripped (anchor text remains), original socios.com link preserved
    assert "https://uefa.com/venues" not in draft
    assert "UEFA" in draft
    assert "[Socios](https://www.socios.com/palermo)" in draft






