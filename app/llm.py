from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx


logger = logging.getLogger(__name__)


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        fallback_model: str,
        api_key: str,
        timeout_seconds: float,
        max_tokens: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback_model = fallback_model.strip()
        self.api_key = api_key
        self.max_tokens = max_tokens
        self._api_mode = "chat_completions"
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        timeout = httpx.Timeout(
            connect=max(3.0, self.timeout_seconds),
            read=max(60.0, self.timeout_seconds),
            write=max(3.0, self.timeout_seconds),
            pool=10.0,
        )
        self._stream_timeout = httpx.Timeout(
            connect=max(3.0, self.timeout_seconds),
            read=max(300.0, self.timeout_seconds * 4.0),
            write=max(3.0, self.timeout_seconds),
            pool=10.0,
        )
        limits = httpx.Limits(max_connections=24, max_keepalive_connections=12, keepalive_expiry=90.0)
        self._client = httpx.Client(timeout=timeout, limits=limits)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def api_mode(self) -> str:
        return self._api_mode

    def _modes_to_try(self) -> list[str]:
        if self._api_mode == "responses":
            return ["responses", "chat_completions"]
        return ["chat_completions", "responses"]

    def _request_url(self, mode: str) -> str:
        if mode == "responses":
            return f"{self.base_url}/responses"
        return f"{self.base_url}/chat/completions"

    def _payload(self, mode: str, model: str, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
        if mode == "responses":
            return {
                "model": model,
                "input": messages,
                "temperature": 0.15,
                "max_output_tokens": self.max_tokens,
                "stream": stream,
            }
        return {
            "model": model,
            "messages": messages,
            "temperature": 0.15,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    def _extract_content(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(str(item.get("text")))
            return "".join(parts)
        return ""

    def _extract_stream_piece(self, payload: dict[str, Any]) -> str:
        event_type = str(payload.get("type", "")).strip().lower()
        if event_type in {"response.output_text.delta", "output_text.delta"}:
            delta = payload.get("delta", "")
            return delta if isinstance(delta, str) else ""
        if event_type in {"response.completed", "response.output_text.done", "output_text.done"}:
            return ""
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, str):
                            parts.append(item)
                            continue
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            parts.append(str(item.get("text")))
                    return "".join(parts)
        return ""

    def _format_request_error(self, mode: str, exc: httpx.HTTPError) -> RuntimeError:
        url = self._request_url(mode)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return RuntimeError(f"LLM request failed: POST {url} -> HTTP {status}")
        return RuntimeError(f"LLM request failed: POST {url} -> {exc}")

    def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            return self._chat(self.model, messages)
        except RuntimeError as exc:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            logger.warning("LLM primary failed (%s), switching to fallback model=%s", type(exc).__name__, self.fallback_model)
            return self._chat(self.fallback_model, messages)

    def _chat(self, model: str, messages: list[dict[str, str]], timeout: httpx.Timeout | None = None) -> str:
        last_error: RuntimeError | None = None
        for mode in self._modes_to_try():
            try:
                response = self._client.post(
                    self._request_url(mode),
                    headers=self._headers(),
                    json=self._payload(mode, model, messages, False),
                    timeout=timeout,
                )
                response.raise_for_status()
                content = self._extract_content(response.json()).strip()
                if not content:
                    raise RuntimeError("empty_llm_response")
                self._api_mode = mode
                return content
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404 and mode == "chat_completions":
                    logger.info("LLM endpoint %s returned 404, trying Responses API fallback", self._request_url(mode))
                    last_error = self._format_request_error(mode, exc)
                    continue
                raise self._format_request_error(mode, exc) from exc
            except httpx.HTTPError as exc:
                raise self._format_request_error(mode, exc) from exc
            except RuntimeError as exc:
                last_error = exc
                if str(exc) != "empty_llm_response" or mode != "chat_completions":
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("empty_llm_response")

    def chat_stream(self, messages: list[dict[str, str]], on_chunk: Callable[[str], None]) -> str:
        try:
            return self._chat_stream(self.model, messages, on_chunk)
        except httpx.ReadTimeout:
            logger.warning("LLM stream timed out, falling back to non-stream response")
            full = self._chat(self.model, messages, timeout=self._stream_timeout)
            if full:
                on_chunk(full)
            return full
        except RuntimeError as exc:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            logger.warning("LLM primary stream failed (%s), switching to fallback model=%s", type(exc).__name__, self.fallback_model)
            return self._chat_stream(self.fallback_model, messages, on_chunk)

    def _chat_stream(self, model: str, messages: list[dict[str, str]], on_chunk: Callable[[str], None]) -> str:
        last_error: RuntimeError | None = None
        for mode in self._modes_to_try():
            collected: list[str] = []
            try:
                with self._client.stream(
                    "POST",
                    self._request_url(mode),
                    headers=self._headers(),
                    json=self._payload(mode, model, messages, True),
                    timeout=self._stream_timeout,
                ) as response:
                    response.raise_for_status()
                    for raw_line in response.iter_lines():
                        line = str(raw_line or "").strip()
                        if not line or line.startswith(":") or line.startswith("event:"):
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        piece = self._extract_stream_piece(payload)
                        if not piece:
                            continue
                        collected.append(piece)
                        on_chunk(piece)
                if not collected:
                    full = self._chat(model, messages, timeout=self._stream_timeout)
                    on_chunk(full)
                    return full
                self._api_mode = mode
                return "".join(collected).strip()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404 and mode == "chat_completions":
                    logger.info("LLM stream endpoint %s returned 404, trying Responses API fallback", self._request_url(mode))
                    last_error = self._format_request_error(mode, exc)
                    continue
                raise self._format_request_error(mode, exc) from exc
            except httpx.HTTPError as exc:
                raise self._format_request_error(mode, exc) from exc
            except RuntimeError as exc:
                last_error = exc
                if str(exc) != "empty_llm_response" or mode != "chat_completions":
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("empty_llm_response")

    def close(self) -> None:
        self._client.close()
