import pytest
import hashlib
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
            # 3. Known fields overwritten with extracted data
            assert json_ld["headline"] == "Real Page Title"
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
