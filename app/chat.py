from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable

from .cache import TTLCache
from .config import Settings
from .llm import LlmClient
from .mcp import MCPRegistry


logger = logging.getLogger(__name__)


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

    def clear(self, session_id: str) -> None:
        self._rows.pop(session_id, None)


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
                "Du bist woddi-ai-control, ein MCP-zentrierter technischer Assistent fuer "
                "woddi-ai, Satelliten, lokale Dateien, Doku und NetBox. Arbeite praezise, "
                "nenne Unsicherheiten offen und halluziniere keine Fakten."
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

    def _selected_mcp_ids(self, metadata: dict[str, Any]) -> set[str]:
        raw = metadata.get("selected_mcp_ids")
        if isinstance(raw, list):
            return {str(item).strip() for item in raw if str(item).strip()}
        return set()

    def _prompt_from_metadata(self, metadata: dict[str, Any]) -> str:
        inline_prompt = str(metadata.get("system_prompt", "")).strip()
        if inline_prompt:
            return inline_prompt
        return self.system_prompt

    def _should_use_netbox(self, message: str, selected_mcp_ids: set[str]) -> bool:
        del message
        return bool(selected_mcp_ids)

    def _should_use_files(self, selected_mcp_ids: set[str]) -> bool:
        return bool(selected_mcp_ids)

    def _extract_netbox_query(self, message: str) -> str:
        quoted = re.findall(r'"([^"]+)"', message)
        if quoted:
            return quoted[0].strip()
        ip_matches = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b", message)
        if ip_matches:
            return ip_matches[0].strip()
        tokens = re.findall(r"[a-zA-Z0-9_.:/-]+", message)
        stop_words = {
            "bitte",
            "zeige",
            "such",
            "suche",
            "finde",
            "welche",
            "welcher",
            "welches",
            "gibt",
            "es",
            "in",
            "der",
            "die",
            "das",
            "mit",
            "aus",
            "von",
            "zu",
            "und",
            "oder",
            "netbox",
            "server",
            "host",
            "hostname",
            "maschine",
            "geraet",
            "device",
            "devices",
            "objekt",
            "objekte",
            "vm",
            "virtual",
            "machine",
            "machines",
        }
        likely_asset_tokens = [
            token
            for token in tokens
            if len(token) > 2
            and token.lower() not in stop_words
            and (
                "." in token
                or "-" in token
                or "_" in token
                or any(character.isdigit() for character in token)
            )
        ]
        if likely_asset_tokens:
            return " ".join(likely_asset_tokens[:2]).strip()
        filtered = [token for token in tokens if len(token) > 2 and token.lower() not in stop_words]
        return " ".join(filtered[:3]).strip()

    def _guess_netbox_object_types(self, message: str) -> list[str]:
        lower = message.lower()
        candidates: list[str] = []
        if "prefix" in lower or "subnet" in lower or "cidr" in lower:
            candidates.extend(["prefixes", "ip-addresses"])
        elif "ip" in lower or re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}", lower):
            candidates.extend(["ip-addresses", "interfaces", "devices", "virtual-machines"])
        elif "interface" in lower or "port" in lower:
            candidates.extend(["interfaces", "devices"])
        elif "site" in lower or "standort" in lower or "az " in f" {lower} ":
            candidates.extend(["sites", "clusters", "devices"])
        elif "rack" in lower:
            candidates.extend(["racks", "devices"])
        elif "tenant" in lower or "kunde" in lower:
            candidates.extend(["tenants", "devices", "virtual-machines"])
        elif "cluster" in lower:
            candidates.extend(["clusters", "virtual-machines", "devices"])
        elif "virtual machine" in lower or " vm " in f" {lower} " or "virtuelle maschine" in lower:
            candidates.extend(["virtual-machines", "devices"])
        elif any(token in lower for token in {"server", "host", "hostname", "appliance", "node", "device", "maschine", "system"}):
            candidates.extend(["devices", "virtual-machines", "ip-addresses"])
        else:
            candidates.extend(["devices", "virtual-machines", "ip-addresses", "interfaces"])

        ordered: list[str] = []
        for candidate in candidates:
            if candidate not in ordered:
                ordered.append(candidate)
        return ordered

    def _guess_netbox_payload(self, message: str) -> dict[str, Any]:
        candidates = self._guess_netbox_object_types(message)
        object_type = candidates[0] if candidates else "devices"
        query = self._extract_netbox_query(message)
        filters: dict[str, Any] = {"limit": 8}
        if query:
            filters["q"] = query
        return {
            "action": "get_objects",
            "object_type": object_type,
            "candidate_object_types": candidates,
            "filters": filters,
        }

    def _gather_docs_context(self, message: str, selected_mcp_ids: set[str]) -> tuple[list[str], list[str], list[dict[str, Any]], dict[str, Any]]:
        started_at = time.perf_counter()
        context_blocks: list[str] = []
        citations: list[str] = []
        mcp_results: list[dict[str, Any]] = []
        chars = 0
        searches = 0
        cache_hits = 0
        index_cache_hits = 0
        index_memory_hits = 0
        sources_considered = 0
        for mcp in self.registry.docs_only():
            if selected_mcp_ids and mcp.mcp_id not in selected_mcp_ids:
                continue
            sources_considered += 1
            search_started_at = time.perf_counter()
            result = mcp.search(message, self.settings.docs_top_k)
            searches += 1
            if result.data.get("cache_hit"):
                cache_hits += 1
            if result.data.get("index_cache_hit"):
                index_cache_hits += 1
            if result.data.get("index_memory_hit"):
                index_memory_hits += 1
            result_payload = result.as_dict()
            result_payload["duration_ms"] = round((time.perf_counter() - search_started_at) * 1000.0, 2)
            mcp_results.append(result_payload)
            if not result.success:
                continue
            rows = result.data.get("results", [])
            if not isinstance(rows, list):
                continue
            top_rows = [row for row in rows if float(row.get("score", 0.0)) > 0.08][: self.settings.docs_top_k]
            if not top_rows:
                continue
            for idx, row in enumerate(top_rows, start=1):
                block = f"[{mcp.label} #{idx}] {row['source']}\n{row['text']}\n"
                if chars + len(block) > self.settings.context_max_chars:
                    break
                chars += len(block)
                context_blocks.append(block)
                source = f"{mcp.label}: {row['source']}"
                if source not in citations:
                    citations.append(source)
        return context_blocks, citations, mcp_results, {
            "docs_duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
            "docs_searches": searches,
            "docs_cache_hits": cache_hits,
            "docs_index_cache_hits": index_cache_hits,
            "docs_index_memory_hits": index_memory_hits,
            "docs_sources_considered": sources_considered,
            "docs_context_chars": chars,
            "docs_citations": len(citations),
        }

    def _gather_files_context(self, message: str, selected_mcp_ids: set[str]) -> tuple[str, list[str], list[dict[str, Any]], dict[str, Any]]:
        started_at = time.perf_counter()
        file_mcps = [mcp for mcp in self.registry.files_only() if not selected_mcp_ids or mcp.mcp_id in selected_mcp_ids]
        if not file_mcps:
            return "", [], [], {"files_used": False, "files_duration_ms": 0.0, "files_cache_hit": False}
        perf = {
            "files_used": True,
            "files_duration_ms": 0.0,
            "files_cache_hit": False,
        }
        context_lines: list[str] = []
        citations: list[str] = []
        results: list[dict[str, Any]] = []
        cache_hit = False
        for mcp in file_mcps:
            result = self.registry.execute(mcp.mcp_id, "search", {"query": message, "limit": min(5, self.settings.files_search_max_results)})
            result_payload = result.as_dict()
            results.append(result_payload)
            if isinstance(result.data, dict) and result.data.get("cache_hit"):
                cache_hit = True
            if not result.success:
                continue
            rows = result.data.get("results", []) if isinstance(result.data, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows[:3]:
                if not isinstance(row, dict):
                    continue
                root_name = str(row.get("root_name", row.get("root_id", mcp.label))).strip()
                path = str(row.get("path", "")).strip()
                preview = str(row.get("preview", "")).strip()
                context_lines.append(f"[{mcp.label} / {root_name}] {path}\n{preview}")
                citations.append(f"{mcp.label}: {path}")
        perf["files_duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        perf["files_cache_hit"] = cache_hit
        if not context_lines:
            return "Files Kontext: keine passenden Dateien gefunden.", [], results, perf
        return "Files Kontext:\n" + "\n\n".join(context_lines), citations, results, perf

    def _gather_netbox_context(self, message: str, selected_mcp_ids: set[str]) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        started_at = time.perf_counter()
        netbox_mcps = [mcp for mcp in self.registry.netbox_only() if not selected_mcp_ids or mcp.mcp_id in selected_mcp_ids]
        if not netbox_mcps or not self._should_use_netbox(message, selected_mcp_ids):
            return "", None, {"netbox_used": False, "netbox_duration_ms": 0.0, "netbox_cache_hit": False}
        target_mcp = netbox_mcps[0]
        payload = self._guess_netbox_payload(message)
        candidate_types = payload.get("candidate_object_types", [])
        if not isinstance(candidate_types, list) or not candidate_types:
            candidate_types = [str(payload.get("object_type", "devices"))]

        result = None
        selected_type = ""
        for candidate_type in candidate_types[:4]:
            candidate_payload = {
                "action": "get_objects",
                "object_type": candidate_type,
                "filters": dict(payload.get("filters", {})),
            }
            current_result = self.registry.execute(target_mcp.mcp_id, "get_objects", candidate_payload)
            if result is None:
                result = current_result
                selected_type = candidate_type
            if not current_result.success:
                continue
            rows = current_result.data.get("results", [])
            if isinstance(rows, list) and rows:
                result = current_result
                selected_type = candidate_type
                break
        assert result is not None
        perf = {
            "netbox_used": True,
            "netbox_duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
            "netbox_cache_hit": bool(result.data.get("cache_hit")),
            "netbox_object_type": selected_type,
        }
        if not result.success:
            return f"NetBox Hinweis: {result.message}", result.as_dict(), perf
        rows = result.data.get("results", [])
        if not isinstance(rows, list):
            rows = []
        if not rows:
            return "NetBox Kontext: keine passenden Objekte gefunden.", result.as_dict(), perf
        preview_rows = rows[:5]
        serialized = json.dumps(preview_rows, ensure_ascii=False, indent=2)
        return f"NetBox Kontext ({selected_type}):\n{serialized}", result.as_dict(), perf


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
                    "docs_duration_ms": 0.0,
                    "docs_searches": 0,
                    "docs_cache_hits": 0,
                    "docs_index_cache_hits": 0,
                    "docs_index_memory_hits": 0,
                    "netbox_used": False,
                    "netbox_duration_ms": 0.0,
                    "scopes_count": len(self._selected_mcp_ids(metadata)),
                    "direct_mcp": f"{mcp_id}:{action}",
                },
            }

        selected_mcp_ids = self._selected_mcp_ids(metadata)
        docs_context, citations, doc_results, docs_perf = self._gather_docs_context(message, selected_mcp_ids)
        netbox_context, netbox_result, netbox_perf = self._gather_netbox_context(message, selected_mcp_ids)
        files_context, file_citations, file_results, files_perf = self._gather_files_context(message, selected_mcp_ids)
        citations.extend(item for item in file_citations if item not in citations)
        history = self.memory.history(session)

        tool_descriptions = "\n".join([f"- {item['label']} ({item['id']}): {item['description']}" for item in self.registry.list()])
        context_text = "\n".join(docs_context).strip()
        if netbox_context:
            context_text = f"{context_text}\n\n{netbox_context}".strip()
        if files_context:
            context_text = f"{context_text}\n\n{files_context}".strip()
        if not context_text:
            if selected_mcp_ids:
                all_mcp_results = doc_results + ([netbox_result] if netbox_result else []) + file_results
                reply = (
                    "Ich habe fuer die gewaehlten Scopes keinen MCP-Kontext gefunden. "
                    "Ich nenne daher bewusst keine konkreten Systeme oder Doku-Fakten. "
                    "Bitte pruefe Scope-Auswahl, Datenquelle/Index und stelle die Anfrage praeziser."
                )
                self.memory.append(session, "user", message)
                self.memory.append(session, "assistant", reply)
                total_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                return {
                    "session_id": session,
                    "reply": reply,
                    "route": "mcp_context_missing",
                    "citations": citations,
                    "mcp_results": [item for item in all_mcp_results if item],
                    "request_fingerprint": hashlib.sha1(f"{session}|{message}".encode("utf-8")).hexdigest()[:16],
                    "perf": {
                        **docs_perf,
                        **netbox_perf,
                        **files_perf,
                        "total_ms": total_ms,
                        "input_chars": len(message),
                        "history_messages": len(history),
                        "context_chars": len(context_text),
                        "llm_duration_ms": 0.0,
                        "llm_cache_hit": False,
                        "scopes_count": len(selected_mcp_ids),
                    },
                }
            context_text = "Kein externer MCP-Kontext vorhanden. Antworte nur mit Modellwissen und markiere Unsicherheit klar."

        messages = [
            {"role": "system", "content": self._prompt_from_metadata(metadata)},
            {
                "role": "system",
                "content": (
                    "Verfuegbare interne MCPs:\n"
                    f"{tool_descriptions}\n\n"
                    "Nutze ausschliesslich den gelieferten MCP-Kontext fuer konkrete Aussagen zu internen Dokumenten oder NetBox."
                ),
            },
            {"role": "system", "content": f"MCP-Kontext:\n{context_text}"},
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
        mcp_results = doc_results + ([netbox_result] if netbox_result else []) + file_results
        total_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        return {
            "session_id": session,
            "reply": reply,
            "route": "llm_with_mcp_context",
            "citations": citations,
            "mcp_results": [item for item in mcp_results if item],
            "llm_cache_hit": llm_cache_hit,
            "request_fingerprint": hashlib.sha1(f"{session}|{message}".encode("utf-8")).hexdigest()[:16],
            "perf": {
                **docs_perf,
                **netbox_perf,
                **files_perf,
                "total_ms": total_ms,
                "input_chars": len(message),
                "history_messages": len(history),
                "context_chars": len(context_text),
                "llm_duration_ms": llm_duration_ms,
                "llm_cache_hit": llm_cache_hit,
                "scopes_count": len(selected_mcp_ids),
            },
        }
