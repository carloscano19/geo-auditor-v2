import pytest
import hashlib
import asyncio
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
from main import app, ai_fixes_cache


@pytest.fixture(autouse=True)
def reset_state():
    daily_tracker.reset_for_tests()
    ai_fixes_cache.clear()
    get_settings.cache_clear()
    yield
    daily_tracker.reset_for_tests()
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

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.json.return_value = {"error": "Rate limit exceeded"}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"content": '{"json_ld": {"@type": "Article"}}'}}]
    }

    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_429, mock_resp_200]) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await client.call_chat_completion([{"role": "user", "content": "hello"}])
        assert res["json_ld"]["@type"] == "Article"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(3.0)


@pytest.mark.asyncio
async def test_llm_client_error_sanitization():
    client = LLMClient(
        base_url="https://api.test.com",
        model="gpt-4o",
        api_key="SUPER_SECRET_KEY_123",
        daily_limit=10,
    )

    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal error with SUPER_SECRET_KEY_123"

    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_500, mock_resp_500]), \
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
                    "draft_answer": "According to the article, the conversion rate reached 42 percent https://fake.com/link.",
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

