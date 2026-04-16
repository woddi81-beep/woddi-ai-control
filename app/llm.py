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

    def _payload(self, model: str, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "temperature": 0.15,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    def _extract_content(self, payload: dict[str, Any]) -> str:
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

    def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            return self._chat(self.model, messages)
        except (httpx.HTTPError, RuntimeError) as exc:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            logger.warning("LLM primary failed (%s), switching to fallback model=%s", type(exc).__name__, self.fallback_model)
            return self._chat(self.fallback_model, messages)

    def _chat(self, model: str, messages: list[dict[str, str]], timeout: httpx.Timeout | None = None) -> str:
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(model, messages, False),
            timeout=timeout,
        )
        response.raise_for_status()
        content = self._extract_content(response.json()).strip()
        if not content:
            raise RuntimeError("empty_llm_response")
        return content

    def chat_stream(self, messages: list[dict[str, str]], on_chunk: Callable[[str], None]) -> str:
        try:
            return self._chat_stream(self.model, messages, on_chunk)
        except httpx.ReadTimeout:
            logger.warning("LLM stream timed out, falling back to non-stream response")
            full = self._chat(self.model, messages, timeout=self._stream_timeout)
            if full:
                on_chunk(full)
            return full
        except (httpx.HTTPError, RuntimeError) as exc:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            logger.warning("LLM primary stream failed (%s), switching to fallback model=%s", type(exc).__name__, self.fallback_model)
            return self._chat_stream(self.fallback_model, messages, on_chunk)

    def _chat_stream(self, model: str, messages: list[dict[str, str]], on_chunk: Callable[[str], None]) -> str:
        collected: list[str] = []
        with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(model, messages, True),
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
        return "".join(collected).strip()

    def close(self) -> None:
        self._client.close()
