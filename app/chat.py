from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable

from .cache import TTLCache
from .config import Settings
from .llm import LlmClient
from .mcp import MCPRegistry


class SlidingWindowRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = max(1, int(limit_per_minute))
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - 60.0
        history = self._history[key]
        while history and history[0] < cutoff:
            history.popleft()
        if len(history) >= self.limit_per_minute:
            return False
        history.append(now)
        return True


class SessionMemory:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._rows: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=self.limit * 2))

    def history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._rows[session_id])

    def append(self, session_id: str, role: str, content: str) -> None:
        self._rows[session_id].append({"role": role, "content": content})


class MonoAssistant:
    def __init__(self, *, settings: Settings, llm: LlmClient, registry: MCPRegistry) -> None:
        self.settings = settings
        self.llm = llm
        self.registry = registry
        self.memory = SessionMemory(settings.chat_history_limit)
        self.limiter = SlidingWindowRateLimiter(settings.chat_rate_limit_per_minute)
        self.system_prompt = self._load_system_prompt()
        self.reply_cache: TTLCache[str] = TTLCache(settings.llm_cache_ttl_seconds, settings.llm_cache_max_entries)

    def _load_system_prompt(self) -> str:
        if not self.settings.system_prompt_path.exists():
            return (
                "Du bist woddi-ai-control, ein kompakter technischer Assistent fuer externe MCP-Module. "
                "Arbeite praezise, nenne Unsicherheit offen und erfinde keine Modulfaehigkeiten."
            )
        return self.settings.system_prompt_path.read_text(encoding="utf-8", errors="replace").strip()

    def _default_session_id(self) -> str:
        return f"mono-{uuid.uuid4().hex[:12]}"

    def _parse_direct_command(self, message: str) -> tuple[str, str, dict[str, Any]] | None:
        stripped = message.strip()
        if not stripped.startswith("/mcp "):
            return None
        match = re.match(r"^/mcp\s+([a-zA-Z0-9_-]+)\s+([a-zA-Z0-9_-]+)(?:\s+(.*))?$", stripped, flags=re.DOTALL)
        if not match:
            return None
        mcp_id = match.group(1)
        action = match.group(2)
        raw_json = (match.group(3) or "").strip()
        payload: dict[str, Any] = {}
        if raw_json:
            try:
                data = json.loads(raw_json)
                if isinstance(data, dict):
                    payload = data
            except json.JSONDecodeError:
                payload = {"query": raw_json}
        return mcp_id, action, payload

    def _selected_mcp_ids(self, metadata: dict[str, Any]) -> list[str]:
        raw = metadata.get("selected_mcp_ids")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    def _prompt_from_metadata(self, metadata: dict[str, Any]) -> str:
        inline_prompt = str(metadata.get("system_prompt", "")).strip()
        return inline_prompt or self.system_prompt

    def _summarize_row(self, row: Any) -> str:
        if not isinstance(row, dict):
            return ""
        preferred_keys = ["title", "name", "display", "label", "summary", "path", "id", "status"]
        parts: list[str] = []
        for key in preferred_keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, (int, float)):
                parts.append(f"{key}={value}")
            if len(parts) >= 3:
                break
        return " | ".join(parts)

    def _gather_module_context(self, message: str, selected_mcp_ids: list[str]) -> tuple[str, list[str], list[dict[str, Any]], dict[str, Any]]:
        started_at = time.perf_counter()
        results: list[dict[str, Any]] = []
        citations: list[str] = []
        context_blocks: list[str] = []
        target_ids = selected_mcp_ids or self.registry.ids()
        queried = 0
        success_count = 0

        for mcp_id in target_ids:
            query_payload = {"query": message, "top_k": self.settings.docs_top_k}
            result = self.registry.execute(mcp_id, "query", query_payload)
            if not result.success:
                result = self.registry.execute(mcp_id, "search", query_payload)
            queried += 1
            result_dict = result.as_dict()
            results.append(result_dict)
            if not result.success:
                continue
            success_count += 1
            data = result.data if isinstance(result.data, dict) else {}
            rows = data.get("results", [])
            if isinstance(rows, list) and rows:
                summaries = [self._summarize_row(row) for row in rows[:5]]
                summaries = [item for item in summaries if item]
                if summaries:
                    block = f"[{mcp_id}]\n" + "\n".join(f"- {item}" for item in summaries)
                    context_blocks.append(block)
                    citations.append(mcp_id)
                    continue
            if isinstance(data.get("summary"), str) and data["summary"].strip():
                context_blocks.append(f"[{mcp_id}]\n- {data['summary'].strip()}")
                citations.append(mcp_id)
                continue
            if isinstance(data.get("response"), dict):
                preview = json.dumps(data["response"], ensure_ascii=False)[:800]
                context_blocks.append(f"[{mcp_id}]\n- raw response: {preview}")
                citations.append(mcp_id)

        context_text = "\n\n".join(context_blocks).strip()
        perf = {
            "modules_duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
            "modules_selected": len(target_ids),
            "modules_queried": queried,
            "modules_successful": success_count,
            "modules_context_chars": len(context_text),
        }
        return context_text, citations, results, perf

    def _llm_cache_key(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def chat(
        self,
        *,
        message: str,
        session_id: str | None,
        metadata: dict[str, Any] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        metadata = metadata or {}
        session = session_id or self._default_session_id()
        if not self.limiter.allow(session):
            raise RuntimeError("rate_limited")

        command = self._parse_direct_command(message)
        if command is not None:
            if not bool(metadata.get("allow_direct_mcp")):
                raise RuntimeError("direct_mcp_disabled")
            mcp_id, action, payload = command
            result = self.registry.execute(mcp_id, action, payload)
            reply = json.dumps(result.as_dict(), ensure_ascii=False, indent=2)
            self.memory.append(session, "user", message)
            self.memory.append(session, "assistant", reply)
            total_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
            return {
                "session_id": session,
                "reply": reply,
                "route": "mcp_direct",
                "citations": [],
                "mcp_results": [result.as_dict()],
                "perf": {
                    "total_ms": total_ms,
                    "input_chars": len(message),
                    "history_messages": 0,
                    "context_chars": 0,
                    "llm_duration_ms": 0.0,
                    "llm_cache_hit": False,
                    "modules_duration_ms": 0.0,
                    "modules_selected": len(self._selected_mcp_ids(metadata)),
                    "modules_queried": 0,
                    "modules_successful": 0,
                    "direct_mcp": f"{mcp_id}:{action}",
                },
            }

        selected_mcp_ids = self._selected_mcp_ids(metadata)
        context_text, citations, mcp_results, modules_perf = self._gather_module_context(message, selected_mcp_ids)
        history = self.memory.history(session)

        tool_rows = metadata.get("tool_descriptions")
        if not isinstance(tool_rows, list):
            tool_rows = self.registry.list()
        tool_descriptions = "\n".join(
            [
                f"- {item['label']} ({item['id']}): {item['description']}"
                for item in tool_rows
                if isinstance(item, dict) and item.get("label") and item.get("id")
            ]
        )

        if not context_text:
            if selected_mcp_ids:
                reply = (
                    "Ich habe aus den gewaehlten Modulen keinen belastbaren Kontext erhalten. "
                    "Ich bleibe daher absichtlich allgemein. Bitte pruefe Modulstatus, Handshake und Query-Action."
                )
                self.memory.append(session, "user", message)
                self.memory.append(session, "assistant", reply)
                total_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                return {
                    "session_id": session,
                    "reply": reply,
                    "route": "mcp_context_missing",
                    "citations": citations,
                    "mcp_results": mcp_results,
                    "request_fingerprint": hashlib.sha1(f"{session}|{message}".encode("utf-8")).hexdigest()[:16],
                    "perf": {
                        **modules_perf,
                        "total_ms": total_ms,
                        "input_chars": len(message),
                        "history_messages": len(history),
                        "context_chars": 0,
                        "llm_duration_ms": 0.0,
                        "llm_cache_hit": False,
                    },
                }
            context_text = "Kein Modulkontext vorhanden. Antworte vorsichtig und markiere Unsicherheit klar."

        messages = [
            {"role": "system", "content": self._prompt_from_metadata(metadata)},
            {
                "role": "system",
                "content": (
                    "Verfuegbare externe MCP-Module:\n"
                    f"{tool_descriptions}\n\n"
                    "Nutze fuer systemspezifische Aussagen primaer den gelieferten Modulkontext."
                ),
            },
            {"role": "system", "content": f"Modulkontext:\n{context_text}"},
            *history,
            {"role": "user", "content": message},
        ]

        cache_key = self._llm_cache_key(messages)
        cached_reply = self.reply_cache.get(cache_key)
        llm_cache_hit = cached_reply is not None
        llm_started_at = time.perf_counter()
        if cached_reply is not None:
            reply = cached_reply
            if on_chunk is not None and reply:
                on_chunk(reply)
        elif on_chunk is not None:
            reply = self.llm.chat_stream(messages, on_chunk=on_chunk)
            self.reply_cache.set(cache_key, reply)
        else:
            reply = self.llm.chat(messages)
            self.reply_cache.set(cache_key, reply)
        llm_duration_ms = round((time.perf_counter() - llm_started_at) * 1000.0, 2)

        self.memory.append(session, "user", message)
        self.memory.append(session, "assistant", reply)
        total_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        return {
            "session_id": session,
            "reply": reply,
            "route": "llm_with_mcp_context",
            "citations": citations,
            "mcp_results": mcp_results,
            "llm_cache_hit": llm_cache_hit,
            "request_fingerprint": hashlib.sha1(f"{session}|{message}".encode("utf-8")).hexdigest()[:16],
            "perf": {
                **modules_perf,
                "total_ms": total_ms,
                "input_chars": len(message),
                "history_messages": len(history),
                "context_chars": len(context_text),
                "llm_duration_ms": llm_duration_ms,
                "llm_cache_hit": llm_cache_hit,
            },
        }
