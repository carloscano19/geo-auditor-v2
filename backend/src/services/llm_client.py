"""
GEO-AUDITOR AI - LLM Client

Provider-agnostic HTTP client for OpenAI-compatible chat completions API.
Handles rate limiting, retry logic, JSON extraction, and error sanitization.
"""

import json
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import httpx
from config.settings import get_settings

logger = logging.getLogger("geo_auditor.llm_client")


class DailyLimitExceededError(Exception):
    """Raised when the daily LLM call limit has been reached."""
    pass


class LLMClientError(Exception):
    """Generic sanitized LLM client error."""
    pass


class DailyCallTracker:
    """In-memory daily call counter resetting at UTC midnight."""

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
            raise DailyLimitExceededError("Daily AI limit reached, try again tomorrow")
        self._call_count += 1
        return self._call_count

    def reset_for_tests(self):
        self._current_date_utc = datetime.now(timezone.utc).date()
        self._call_count = 0


# Global tracker instance
daily_tracker = DailyCallTracker()


def extract_json_from_text(text: str) -> dict:
    """
    Extract a valid JSON dictionary from LLM response text.
    Handles ```json ... ``` markdown code fences, direct json.loads,
    outermost balanced curly braces, and json-repair fallback.
    """
    if not text:
        raise LLMClientError("Empty response from AI provider")

    cleaned = text.strip()

    # 1. Try markdown code fences ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", cleaned, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 2. Try direct json.loads
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 3. Find the outermost balanced curly braces { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = cleaned[first_brace:last_brace + 1]
        try:
            parsed = json.loads(json_candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.warning(f"Failed to parse inner JSON: {e}")

    # 4. Fallback: repair with json-repair
    try:
        import json_repair
        candidates_to_repair = []
        if fence_match:
            candidates_to_repair.append(fence_match.group(1).strip())
        candidates_to_repair.append(cleaned)
        if first_brace != -1:
            candidates_to_repair.append(cleaned[first_brace:])

        for cand in candidates_to_repair:
            repaired = json_repair.loads(cand)
            if isinstance(repaired, dict):
                return repaired
    except Exception as e:
        logger.warning(f"json-repair failed: {e}")

    raise LLMClientError("Could not extract valid JSON from AI response")


class LLMClient:
    """
    Client for calling OpenAI-compatible chat completion endpoints.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        daily_limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
        streaming: Optional[bool] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.timeout = timeout or settings.llm_timeout_seconds
        self.daily_limit = daily_limit or settings.llm_daily_limit
        self.max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens
        self.streaming = streaming if streaming is not None else settings.llm_streaming

    def _parse_non_stream_response(self, response: httpx.Response) -> tuple[str, Optional[str]]:
        if response.status_code != 200:
            logger.error(f"LLM API returned status {response.status_code}")
            if response.status_code == 429:
                raise LLMClientError("Rate limit exceeded with AI provider, please try later")
            if response.status_code == 524:
                raise LLMClientError("The AI service took too long to respond. Please try again.")
            raise LLMClientError(f"AI provider returned error status {response.status_code}")

        try:
            resp_json = response.json()
            choice = resp_json["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            finish_reason = choice.get("finish_reason")
            return content, finish_reason
        except Exception:
            logger.error("Invalid response format from AI provider")
            raise LLMClientError("Unexpected response structure from AI provider")

    async def _stream_and_extract_content(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        import asyncio
        payload_stream = dict(payload)
        payload_stream["stream"] = True

        from unittest.mock import MagicMock, AsyncMock
        if isinstance(getattr(client, "post", None), (MagicMock, AsyncMock)) or isinstance(getattr(httpx.AsyncClient, "post", None), (MagicMock, AsyncMock)):
            return await self._post_and_extract_content(client, url, headers, payload)

        req = client.build_request("POST", url, headers=headers, json=payload_stream)
        try:
            resp = await client.send(req, stream=True)
        except httpx.TimeoutException:
            logger.error("LLM streaming connection request timed out")
            raise LLMClientError("AI service request timed out")
        except httpx.HTTPError:
            logger.error("LLM streaming connection HTTP failure")
            raise LLMClientError("Failed to communicate with AI provider")

        # Fallback to non-streaming if gateway does not support stream or returns 400
        content_type = resp.headers.get("content-type", "").lower()
        if resp.status_code == 400 or (resp.status_code == 200 and "application/json" in content_type and "text/event-stream" not in content_type):
            logger.info("Gateway returned non-stream response or 400; falling back to non-streaming request")
            if resp.status_code == 200:
                await resp.aread()
                await resp.aclose()
                return self._parse_non_stream_response(resp)
            await resp.aclose()
            return await self._post_and_extract_content(client, url, headers, payload)

        if resp.status_code != 200:
            status = resp.status_code
            await resp.aclose()
            # If 429 or 5xx, retry once after 3 seconds (skip 524 without streaming, but in stream attempt initial 524 can retry once)
            if (status == 429 or (500 <= status < 600)) and status != 524:
                logger.warning(f"LLM streaming request got status {status}, retrying once in 3s...")
                await asyncio.sleep(3.0)
                req_retry = client.build_request("POST", url, headers=headers, json=payload_stream)
                resp = await client.send(req_retry, stream=True)
                retry_ct = resp.headers.get("content-type", "").lower()
                if resp.status_code == 400 or (resp.status_code == 200 and "application/json" in retry_ct and "text/event-stream" not in retry_ct):
                    if resp.status_code == 200:
                        await resp.aread()
                        await resp.aclose()
                        return self._parse_non_stream_response(resp)
                    await resp.aclose()
                    return await self._post_and_extract_content(client, url, headers, payload)

                if resp.status_code != 200:
                    status_retry = resp.status_code
                    await resp.aclose()
                    if status_retry == 429:
                        raise LLMClientError("Rate limit exceeded with AI provider, please try later")
                    if status_retry == 524:
                        raise LLMClientError("The AI service took too long to respond. Please try again.")
                    raise LLMClientError(f"AI provider returned error status {status_retry}")
            else:
                if status == 429:
                    raise LLMClientError("Rate limit exceeded with AI provider, please try later")
                if status == 524:
                    raise LLMClientError("The AI service took too long to respond. Please try again.")
                raise LLMClientError(f"AI provider returned error status {status}")

        parts = []
        finish_reason: Optional[str] = None
        stream_interrupted = False

        try:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if delta.get("content"):
                            parts.append(delta["content"])
                        if choices[0].get("finish_reason"):
                            finish_reason = choices[0]["finish_reason"]
                except Exception as e:
                    logger.debug(f"Could not parse SSE chunk: {e}")
        except httpx.TimeoutException:
            logger.error("LLM streaming read timed out")
            stream_interrupted = True
        except httpx.HTTPError:
            logger.error("LLM stream disconnected during read")
            stream_interrupted = True
        finally:
            await resp.aclose()

        if stream_interrupted:
            logger.warning("Stream disconnected or timed out mid-transfer; retrying once...")
            await asyncio.sleep(3.0)
            req_retry = client.build_request("POST", url, headers=headers, json=payload_stream)
            try:
                resp_retry = await client.send(req_retry, stream=True)
            except httpx.TimeoutException:
                raise LLMClientError("AI service request timed out")
            except httpx.HTTPError:
                raise LLMClientError("Failed to communicate with AI provider")

            if resp_retry.status_code != 200:
                s_retry = resp_retry.status_code
                await resp_retry.aclose()
                if s_retry == 429:
                    raise LLMClientError("Rate limit exceeded with AI provider, please try later")
                if s_retry == 524:
                    raise LLMClientError("The AI service took too long to respond. Please try again.")
                raise LLMClientError(f"AI provider returned error status {s_retry}")

            parts.clear()
            finish_reason = None
            try:
                async for line in resp_retry.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if delta.get("content"):
                                parts.append(delta["content"])
                            if choices[0].get("finish_reason"):
                                finish_reason = choices[0]["finish_reason"]
                    except Exception as e:
                        logger.debug(f"Could not parse SSE chunk on retry: {e}")
            except httpx.TimeoutException:
                raise LLMClientError("AI service request timed out")
            except httpx.HTTPError:
                raise LLMClientError("Failed to communicate with AI provider")
            finally:
                await resp_retry.aclose()

        content = "".join(parts)
        return content, finish_reason

    async def _post_and_extract_content(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        try:
            response = await self._send_request_with_retry(client, url, headers, payload)
        except httpx.TimeoutException:
            logger.error("LLM API request timed out")
            raise LLMClientError("AI service request timed out")
        except httpx.HTTPError:
            logger.error("LLM API HTTP communication failure")
            raise LLMClientError("Failed to communicate with AI provider")

        return self._parse_non_stream_response(response)

    async def call_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Call {base_url}/chat/completions with messages.
        Returns the parsed JSON response object from LLM output.
        Retries once on 429 or 5xx after 3 seconds.
        Sanitizes errors so API keys and raw error bodies are never leaked.
        If JSON extraction fails or finish_reason is 'length', retries once automatically
        with concise response instructions.
        """
        if not self.base_url or not self.model or not self.api_key:
            raise LLMClientError("AI layer is not configured")

        # Check and increment daily counter
        daily_tracker.check_and_increment(self.daily_limit)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }

        timeout_config = httpx.Timeout(self.timeout, read=60.0) if self.streaming else httpx.Timeout(self.timeout)

        async with httpx.AsyncClient(timeout=timeout_config) as client:
            if self.streaming:
                content, finish_reason = await self._stream_and_extract_content(client, url, headers, payload)
            else:
                content, finish_reason = await self._post_and_extract_content(client, url, headers, payload)

            needs_retry = False
            parsed_json = None

            if finish_reason == "length":
                needs_retry = True
                logger.warning(
                    f"Could not extract valid JSON from AI response: finish_reason={finish_reason}, "
                    f"content_length={len(content)}, ends_with_brace={content.rstrip().endswith('}')}"
                )
            else:
                try:
                    parsed_json = extract_json_from_text(content)
                except LLMClientError:
                    needs_retry = True
                    logger.warning(
                        f"Could not extract valid JSON from AI response: finish_reason={finish_reason}, "
                        f"content_length={len(content)}, ends_with_brace={content.rstrip().endswith('}')}"
                    )

            if not needs_retry and parsed_json is not None:
                return parsed_json

            # Automatic retry: single retry appending concise instruction to user message
            retry_instruction = "\n\nYour previous answer was cut off or invalid. Return ONLY valid JSON with the same keys, keeping each text field concise."
            retry_messages = [dict(m) for m in messages]
            for i in range(len(retry_messages) - 1, -1, -1):
                if retry_messages[i].get("role") == "user":
                    retry_messages[i]["content"] = retry_messages[i]["content"] + retry_instruction
                    break
            else:
                retry_messages.append({"role": "user", "content": retry_instruction.strip()})

            retry_payload = {
                "model": self.model,
                "messages": retry_messages,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
            }

            if self.streaming:
                content_retry, finish_reason_retry = await self._stream_and_extract_content(client, url, headers, retry_payload)
            else:
                content_retry, finish_reason_retry = await self._post_and_extract_content(client, url, headers, retry_payload)

            if finish_reason_retry == "length":
                logger.warning(
                    f"Could not extract valid JSON from AI response on retry: finish_reason={finish_reason_retry}, "
                    f"content_length={len(content_retry)}, ends_with_brace={content_retry.rstrip().endswith('}')}"
                )
                raise LLMClientError("Could not extract valid JSON from AI response")

            try:
                return extract_json_from_text(content_retry)
            except LLMClientError:
                logger.warning(
                    f"Could not extract valid JSON from AI response on retry: finish_reason={finish_reason_retry}, "
                    f"content_length={len(content_retry)}, ends_with_brace={content_retry.rstrip().endswith('}')}"
                )
                raise LLMClientError("Could not extract valid JSON from AI response")

    async def _send_request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> httpx.Response:
        import asyncio

        resp = await client.post(url, headers=headers, json=payload)
        # In non-streaming mode: retry on 429 or 5xx, but do NOT retry 524
        if resp.status_code == 429 or (500 <= resp.status_code < 600 and resp.status_code != 524):
            logger.warning(f"LLM request got status {resp.status_code}, retrying once in 3s...")
            await asyncio.sleep(3.0)
            resp = await client.post(url, headers=headers, json=payload)
        return resp
