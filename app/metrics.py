from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile))
    index = max(0, min(len(ordered) - 1, index))
    return round(ordered[index], 2)


def _rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


@dataclass
class MetricEvent:
    timestamp: float
    category: str
    name: str
    duration_ms: float
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)


class PerformanceTracker:
    def __init__(self, max_events: int = 800, window_seconds: int = 1800) -> None:
        self.max_events = max(100, int(max_events))
        self.window_seconds = max(60, int(window_seconds))
        self._events: deque[MetricEvent] = deque(maxlen=self.max_events)
        self._lock = threading.Lock()

    def record(
        self,
        category: str,
        name: str,
        duration_ms: float,
        *,
        ok: bool = True,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = MetricEvent(
            timestamp=time.time(),
            category=category.strip() or "unknown",
            name=name.strip() or "unknown",
            duration_ms=round(max(0.0, float(duration_ms)), 2),
            ok=bool(ok),
            data=dict(data or {}),
        )
        with self._lock:
            self._events.append(event)

    def _window_events(self) -> list[MetricEvent]:
        cutoff = time.time() - self.window_seconds
        with self._lock:
            return [event for event in self._events if event.timestamp >= cutoff]

    def _build_summary(self, events: list[MetricEvent]) -> list[dict[str, Any]]:
        groups: dict[str, list[MetricEvent]] = {}
        for event in events:
            groups.setdefault(event.name, []).append(event)
        rows: list[dict[str, Any]] = []
        for name, group in groups.items():
            durations = [item.duration_ms for item in group]
            rows.append(
                {
                    "name": name,
                    "count": len(group),
                    "error_count": sum(1 for item in group if not item.ok),
                    "avg_ms": _mean(durations),
                    "p95_ms": _percentile(durations, 0.95),
                    "max_ms": round(max(durations), 2) if durations else 0.0,
                }
            )
        rows.sort(key=lambda item: (item["avg_ms"], item["max_ms"]), reverse=True)
        return rows

    def _recent_rows(self, events: list[MetricEvent], limit: int = 16) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in reversed(events[-limit:]):
            payload = event.data
            parts = [f"{event.name} {event.duration_ms:.0f} ms"]
            reason = str(payload.get("reason", "")).strip()
            first_token_ms = payload.get("first_token_ms")
            if isinstance(first_token_ms, (int, float)) and first_token_ms > 0:
                parts.append(f"TTFT {float(first_token_ms):.0f} ms")
            if payload.get("llm_cache_hit"):
                parts.append("LLM cache")
            if payload.get("docs_cache_hits"):
                parts.append(f"Docs cache {payload.get('docs_cache_hits')}/{payload.get('docs_searches', 0)}")
            if payload.get("netbox_used"):
                netbox_label = "NetBox cache" if payload.get("netbox_cache_hit") else "NetBox"
                parts.append(netbox_label)
            if payload.get("files_used"):
                files_label = "Files cache" if payload.get("files_cache_hit") else "Files"
                parts.append(files_label)
            if reason:
                parts.append(f"reason={reason}")
            rows.append(
                {
                    "timestamp_utc": datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat(),
                    "category": event.category,
                    "name": event.name,
                    "ok": event.ok,
                    "duration_ms": event.duration_ms,
                    "summary": " | ".join(parts),
                }
            )
        return rows

    def snapshot(self) -> dict[str, Any]:
        events = self._window_events()
        chat_events = [event for event in events if event.category == "chat"]
        endpoint_events = [event for event in events if event.category == "endpoint"]
        mcp_events = [event for event in events if event.category == "mcp"]

        chat_durations = [event.duration_ms for event in chat_events]
        first_token_values = [
            float(event.data["first_token_ms"])
            for event in chat_events
            if isinstance(event.data.get("first_token_ms"), (int, float)) and float(event.data["first_token_ms"]) > 0
        ]
        llm_durations = [
            float(event.data["llm_duration_ms"])
            for event in chat_events
            if isinstance(event.data.get("llm_duration_ms"), (int, float))
        ]
        docs_durations = [
            float(event.data["docs_duration_ms"])
            for event in chat_events
            if isinstance(event.data.get("docs_duration_ms"), (int, float))
        ]
        docs_searches = sum(int(event.data.get("docs_searches", 0)) for event in chat_events)
        docs_cache_hits = sum(int(event.data.get("docs_cache_hits", 0)) for event in chat_events)
        docs_index_cache_hits = sum(int(event.data.get("docs_index_cache_hits", 0)) for event in chat_events)
        docs_index_memory_hits = sum(int(event.data.get("docs_index_memory_hits", 0)) for event in chat_events)
        netbox_used = sum(1 for event in chat_events if event.data.get("netbox_used"))
        netbox_cache_hits = sum(1 for event in chat_events if event.data.get("netbox_used") and event.data.get("netbox_cache_hit"))
        files_used = sum(1 for event in chat_events if event.data.get("files_used"))
        files_cache_hits = sum(1 for event in chat_events if event.data.get("files_used") and event.data.get("files_cache_hit"))
        llm_cache_hits = sum(1 for event in chat_events if event.data.get("llm_cache_hit"))

        top_endpoint = self._build_summary(endpoint_events)[:1]
        return {
            "generated_at_utc": _now_utc_iso(),
            "window_seconds": self.window_seconds,
            "chat": {
                "total": len(chat_events),
                "error_count": sum(1 for event in chat_events if not event.ok),
                "avg_total_ms": _mean(chat_durations),
                "p95_total_ms": _percentile(chat_durations, 0.95),
                "avg_first_token_ms": _mean(first_token_values),
                "avg_llm_ms": _mean(llm_durations),
                "avg_docs_ms": _mean(docs_durations),
                "llm_cache_hit_rate": _rate(llm_cache_hits, len(chat_events)),
                "files_cache_hit_rate": _rate(files_cache_hits, files_used),
                "routes": self._build_summary(chat_events),
            },
            "docs": {
                "searches": docs_searches,
                "cache_hit_rate": _rate(docs_cache_hits, docs_searches),
                "index_cache_hit_rate": _rate(docs_index_cache_hits, docs_searches),
                "index_memory_hit_rate": _rate(docs_index_memory_hits, docs_searches),
            },
            "netbox": {
                "requests": netbox_used,
                "cache_hit_rate": _rate(netbox_cache_hits, netbox_used),
            },
            "files": {
                "requests": files_used,
                "cache_hit_rate": _rate(files_cache_hits, files_used),
            },
            "endpoints": self._build_summary(endpoint_events),
            "mcp": self._build_summary(mcp_events),
            "top_endpoint": top_endpoint[0] if top_endpoint else None,
            "recent": self._recent_rows(events),
        }
