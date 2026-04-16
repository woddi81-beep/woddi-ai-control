from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .cache import TTLCache
from .config import Settings
from .llm import LlmClient


logger = logging.getLogger(__name__)


def _normalize_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\t+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return _normalize_text(text)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _hash_embedding(text: str, dim: int = 384) -> list[float]:
    vector = [0.0] * dim
    for token in _tokenize(text):
        digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % dim
        vector[idx] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class MCPResult:
    success: bool
    mcp_id: str
    action: str
    message: str
    data: dict[str, Any]
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "mcp_id": self.mcp_id,
            "action": self.action,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }


class BaseMCP(ABC):
    def __init__(self, mcp_id: str, label: str, description: str) -> None:
        self.mcp_id = mcp_id
        self.label = label
        self.description = description

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.mcp_id,
            "label": self.label,
            "description": self.description,
        }

    @abstractmethod
    def execute(self, action: str, payload: dict[str, Any]) -> MCPResult:
        raise NotImplementedError


class DocumentationMCP(BaseMCP):
    def __init__(self, *, source_id: str, label: str, source_path: Path, patterns: list[str], llm: LlmClient, settings: Settings) -> None:
        super().__init__(source_id, label, f"Lokale Dokumentationsquelle {label}")
        self.source_path = source_path
        self.patterns = patterns
        self.llm = llm
        self.settings = settings
        self.source_state_cache: TTLCache[tuple[Path | None, list[Path], str]] = TTLCache(settings.docs_source_scan_cache_ttl_seconds, 4)
        self.source_snapshot_cache: TTLCache[dict[str, Any]] = TTLCache(settings.docs_source_scan_cache_ttl_seconds, 4)
        self.health_cache: TTLCache[dict[str, Any]] = TTLCache(settings.docs_health_cache_ttl_seconds, 4)
        self.search_cache: TTLCache[dict[str, Any]] = TTLCache(settings.docs_search_cache_ttl_seconds, 256)
        self.answer_cache: TTLCache[dict[str, Any]] = TTLCache(settings.docs_answer_cache_ttl_seconds, 128)
        self.index_path = settings.docs_cache_dir / f"{source_id}.index.json"
        self.index_meta_path = settings.docs_cache_dir / f"{source_id}.index.meta.json"
        self._index_lock = threading.Lock()
        self._loaded_index: dict[str, Any] | None = None
        self._loaded_index_digest = ""

    def descriptor(self) -> dict[str, Any]:
        base = super().descriptor()
        base.update(
            {
                "kind": "documentation",
                "source_path": str(self.source_path),
                "index_path": str(self.index_path),
                "index_meta_path": str(self.index_meta_path),
            }
        )
        return base

    def resolve_source_path(self) -> Path:
        return self._coerce_safe_path(self.source_path)

    def clear_runtime_caches(self) -> None:
        self.source_state_cache.clear()
        self.source_snapshot_cache.clear()
        self.health_cache.clear()
        self.search_cache.clear()
        self.answer_cache.clear()
        with self._index_lock:
            self._loaded_index = None
            self._loaded_index_digest = ""

    def execute(self, action: str, payload: dict[str, Any]) -> MCPResult:
        normalized = action.strip().lower() or "search"
        if normalized == "search":
            return self.search(str(payload.get("query", "")).strip(), top_k=int(payload.get("top_k", self.settings.docs_top_k)))
        if normalized == "answer":
            return self.answer(str(payload.get("query", "")).strip(), top_k=int(payload.get("top_k", self.settings.docs_top_k)))
        if normalized == "reindex":
            return self.reindex(force=True)
        if normalized == "stats":
            return self.stats()
        if normalized == "health":
            return self.health()
        return MCPResult(False, self.mcp_id, normalized, "Unbekannte Docs-MCP action.", {}, "invalid_action")

    def _coerce_safe_path(self, path: Path) -> Path:
        candidate = path.expanduser().resolve()
        if self.settings.docs_allow_outside_project:
            return candidate
        project_root = self.settings.base_dir.resolve()
        if project_root not in candidate.parents and candidate != project_root:
            raise ValueError("Pfad ausserhalb Projekt ist blockiert.")
        return candidate

    def _collect_source_files(self, force: bool = False) -> tuple[Path | None, list[Path], str]:
        if not force:
            cached = self.source_state_cache.get("source-files")
            if cached is not None:
                base, files, state = cached
                return base, list(files), state
        base = self._coerce_safe_path(self.source_path)
        if not base.exists():
            payload = (None, [], "missing")
            self.source_state_cache.set("source-files", payload)
            return payload
        if not base.is_dir():
            payload = (None, [], "not_a_directory")
            self.source_state_cache.set("source-files", payload)
            return payload
        files: list[Path] = []
        seen: set[Path] = set()
        for pattern in self.patterns:
            for path in base.glob(pattern):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                files.append(path)
        files.sort()
        payload = (base, files, "ok")
        self.source_state_cache.set("source-files", payload)
        return base, list(files), "ok"

    def _source_snapshot(self, base: Path, files: list[Path]) -> list[list[Any]]:
        snapshot: list[list[Any]] = []
        for path in files:
            stat = path.stat()
            snapshot.append([str(path.relative_to(base)), int(stat.st_size), int(stat.st_mtime_ns)])
        return snapshot

    def _snapshot_digest(self, snapshot: list[list[Any]]) -> str:
        return hashlib.sha1(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _collect_source_snapshot(self, force: bool = False) -> tuple[Path | None, list[Path], str, list[list[Any]], str]:
        if not force:
            cached = self.source_snapshot_cache.get("source-snapshot")
            if cached is not None:
                return (
                    cached.get("base"),
                    list(cached.get("files", [])),
                    str(cached.get("state", "missing")),
                    list(cached.get("snapshot", [])),
                    str(cached.get("snapshot_digest", "")),
                )
        base, files, state = self._collect_source_files(force=force)
        snapshot: list[list[Any]] = []
        snapshot_digest = ""
        if state == "ok" and base is not None:
            snapshot = self._source_snapshot(base, files)
            snapshot_digest = self._snapshot_digest(snapshot)
        payload = {
            "base": base,
            "files": list(files),
            "state": state,
            "snapshot": snapshot,
            "snapshot_digest": snapshot_digest,
        }
        self.source_snapshot_cache.set("source-snapshot", payload)
        return base, list(files), state, snapshot, snapshot_digest

    def _read_documents(self, base: Path, files: list[Path]) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for path in files:
            raw = path.read_text(encoding="utf-8", errors="replace")
            text = _strip_html(raw) if path.suffix.lower() in {".html", ".htm"} else _normalize_text(raw)
            if not text:
                continue
            relative = path.relative_to(base)
            docs.append({"source": str(relative), "text": text, "path": str(path)})
        return docs

    def _chunk_text(self, text: str, chunk_size: int = 220, overlap: int = 40) -> list[str]:
        words = text.split()
        if not words:
            return []
        step = max(1, chunk_size - overlap)
        chunks: list[str] = []
        index = 0
        while index < len(words):
            part = words[index : index + chunk_size]
            if not part:
                break
            chunks.append(" ".join(part))
            if index + chunk_size >= len(words):
                break
            index += step
        return chunks

    def _write_index_meta(self, payload: dict[str, Any]) -> None:
        meta = {
            "source_id": payload.get("source_id", self.mcp_id),
            "documents": int(payload.get("documents", 0)),
            "chunks": len(payload.get("items", [])),
            "source_snapshot_digest": payload.get("source_snapshot_digest", ""),
            "generated_at": payload.get("generated_at"),
        }
        self.index_meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_index_meta(self) -> dict[str, Any]:
        if self.index_meta_path.exists():
            try:
                raw = json.loads(self.index_meta_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except Exception:
                return {}
        return {}

    def _load_index_from_disk(self, snapshot_digest: str) -> dict[str, Any] | None:
        if not self.index_path.exists():
            return None
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict) or raw.get("source_snapshot_digest") != snapshot_digest:
            return None
        self._loaded_index = raw
        self._loaded_index_digest = snapshot_digest
        self._write_index_meta(raw)
        return raw

    def ensure_index(self, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        base, files, state, snapshot, snapshot_digest = self._collect_source_snapshot(force=force)
        if state != "ok" or base is None:
            return {}, {"state": state, "documents": 0, "chunks": 0}
        with self._index_lock:
            if not force and self._loaded_index is not None and self._loaded_index_digest == snapshot_digest:
                return self._loaded_index, {
                    "state": "ready",
                    "documents": len(snapshot),
                    "chunks": len(self._loaded_index.get("items", [])),
                    "index_cache_hit": True,
                    "index_memory_hit": True,
                }
            if not force:
                raw = self._load_index_from_disk(snapshot_digest)
                if raw is not None:
                    return raw, {
                        "state": "ready",
                        "documents": len(snapshot),
                        "chunks": len(raw.get("items", [])),
                        "index_cache_hit": True,
                        "index_memory_hit": False,
                    }

            docs = self._read_documents(base, files)
            items: list[dict[str, Any]] = []
            for doc in docs:
                for chunk_index, chunk in enumerate(self._chunk_text(doc["text"])):
                    items.append(
                        {
                            "id": hashlib.sha1(f"{doc['source']}:{chunk_index}:{chunk}".encode("utf-8")).hexdigest()[:24],
                            "source": doc["source"],
                            "path": doc["path"],
                            "chunk_index": chunk_index,
                            "text": chunk,
                            "embedding": _hash_embedding(chunk),
                        }
                    )
            payload = {
                "source_id": self.mcp_id,
                "documents": len(docs),
                "items": items,
                "source_snapshot": snapshot,
                "source_snapshot_digest": snapshot_digest,
                "generated_at": int(time.time()),
            }
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._write_index_meta(payload)
            self._loaded_index = payload
            self._loaded_index_digest = snapshot_digest
            self.search_cache.clear()
            self.answer_cache.clear()
            self.health_cache.clear()
            return payload, {
                "state": "ready",
                "documents": len(docs),
                "chunks": len(items),
                "index_cache_hit": False,
                "index_memory_hit": False,
            }

    def _search_rows(self, query: str, top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        index, meta = self.ensure_index(force=False)
        if meta.get("state") != "ready":
            return [], meta
        cache_key = hashlib.sha1(f"{query}|{top_k}".encode("utf-8")).hexdigest()
        cached = self.search_cache.get(cache_key)
        if cached is not None:
            return list(cached.get("results", [])), {"cache_hit": True, **meta}
        query_vector = _hash_embedding(query)
        rows: list[dict[str, Any]] = []
        for item in index.get("items", []):
            if not isinstance(item, dict):
                continue
            embedding = item.get("embedding", [])
            if not isinstance(embedding, list):
                continue
            rows.append(
                {
                    "score": _dot(query_vector, embedding),
                    "source": str(item.get("source", "")),
                    "path": str(item.get("path", "")),
                    "chunk_index": int(item.get("chunk_index", 0)),
                    "text": str(item.get("text", "")),
                }
            )
        rows.sort(key=lambda item: item["score"], reverse=True)
        rows = rows[: max(1, top_k)]
        self.search_cache.set(cache_key, {"results": rows})
        return rows, {"cache_hit": False, **meta}

    def search(self, query: str, top_k: int) -> MCPResult:
        if not query:
            return MCPResult(False, self.mcp_id, "search", "Docs-MCP braucht query.", {}, "missing_query")
        rows, meta = self._search_rows(query, top_k)
        if meta.get("state") != "ready":
            return MCPResult(
                False,
                self.mcp_id,
                "search",
                f"Quelle nicht bereit: {meta.get('state')}. Erwarte lokalen Clone unter {self.source_path}.",
                meta,
                "source_unavailable",
            )
        return MCPResult(True, self.mcp_id, "search", f"{len(rows)} Treffer gefunden.", {"results": rows, **meta})

    def answer(self, query: str, top_k: int) -> MCPResult:
        if not query:
            return MCPResult(False, self.mcp_id, "answer", "Docs-MCP braucht query.", {}, "missing_query")
        cache_key = hashlib.sha1(f"{query}|{top_k}|answer".encode("utf-8")).hexdigest()
        cached = self.answer_cache.get(cache_key)
        if cached is not None:
            return MCPResult(True, self.mcp_id, "answer", "Antwort aus Cache geliefert.", cached)
        rows, meta = self._search_rows(query, top_k)
        if meta.get("state") != "ready":
            return MCPResult(
                False,
                self.mcp_id,
                "answer",
                f"Quelle nicht bereit: {meta.get('state')}. Erwarte lokalen Clone unter {self.source_path}.",
                meta,
                "source_unavailable",
            )
        if not rows:
            return MCPResult(False, self.mcp_id, "answer", "Keine Treffer in dieser Dokumentation gefunden.", {"results": []}, "no_matches")
        context_blocks: list[str] = []
        chars = 0
        for idx, row in enumerate(rows):
            block = f"[{idx + 1}] {row['source']}\n{row['text']}\n"
            if chars + len(block) > self.settings.context_max_chars:
                break
            chars += len(block)
            context_blocks.append(block)
        messages = [
            {
                "role": "system",
                "content": (
                    "Du beantwortest Fragen nur aus den gelieferten Dokumentausschnitten. "
                    "Wenn etwas fehlt, sag das offen. Antworte auf Deutsch."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Quelle: {self.label}\n\n"
                    "Kontext:\n"
                    + "\n".join(context_blocks)
                    + f"\n\nFrage: {query}\n\n"
                    "Liefere eine praezise Antwort und danach 'Quellen:' mit Dateipfaden."
                ),
            },
        ]
        answer = self.llm.chat(messages)
        payload = {
            "answer": answer,
            "results": rows,
            "citations": [row["source"] for row in rows if row.get("source")],
            **meta,
        }
        self.answer_cache.set(cache_key, payload)
        return MCPResult(True, self.mcp_id, "answer", "Antwort erzeugt.", payload)

    def reindex(self, force: bool) -> MCPResult:
        _, meta = self.ensure_index(force=force)
        if meta.get("state") != "ready":
            return MCPResult(
                False,
                self.mcp_id,
                "reindex",
                f"Quelle nicht bereit: {meta.get('state')}. Erwarte lokalen Clone unter {self.source_path}.",
                meta,
                "source_unavailable",
            )
        return MCPResult(True, self.mcp_id, "reindex", "Index aktualisiert.", meta)

    def stats(self) -> MCPResult:
        index, meta = self.ensure_index(force=False)
        if meta.get("state") != "ready":
            return MCPResult(
                False,
                self.mcp_id,
                "stats",
                f"Quelle nicht bereit: {meta.get('state')}.",
                meta,
                "source_unavailable",
            )
        return MCPResult(
            True,
            self.mcp_id,
            "stats",
            "Index-Statistik bereit.",
            {
                "documents": int(index.get("documents", 0)),
                "chunks": len(index.get("items", [])),
                "index_path": str(self.index_path),
                "index_generated_at": index.get("generated_at"),
                **meta,
            },
        )

    def health(self) -> MCPResult:
        cached = self.health_cache.get("health")
        if cached is not None:
            return MCPResult(**cached)
        base, files, state, _snapshot, snapshot_digest = self._collect_source_snapshot(force=False)
        ready = state == "ok"
        index_exists = self.index_path.exists()
        index_meta = self._load_index_meta()
        index_matches = bool(index_exists and snapshot_digest and index_meta.get("source_snapshot_digest") == snapshot_digest)
        result = MCPResult(
            success=ready,
            mcp_id=self.mcp_id,
            action="health",
            message="Quelle bereit." if ready else f"Quelle nicht bereit: {state}",
            data={
                "state": state,
                "source_path": str(self.source_path),
                "document_count": len(files),
                "index_path": str(self.index_path),
                "index_meta_path": str(self.index_meta_path),
                "index_exists": index_exists,
                "index_matches_sources": index_matches,
                "index_generated_at": index_meta.get("generated_at"),
            },
            error="" if ready else "source_unavailable",
        )
        self.health_cache.set("health", result.as_dict())
        return result


class FilesMCP(BaseMCP):
    def __init__(
        self,
        *,
        mcp_id: str,
        label: str,
        description: str,
        settings: Settings,
        roots: list[dict[str, Any]],
    ) -> None:
        super().__init__(mcp_id, label, description)
        self.settings = settings
        self.roots = roots
        self.search_cache: TTLCache[dict[str, Any]] = TTLCache(settings.files_search_cache_ttl_seconds, 128)
        self.health_cache: TTLCache[dict[str, Any]] = TTLCache(max(5, min(settings.files_search_cache_ttl_seconds, 30)), 8)

    def descriptor(self) -> dict[str, Any]:
        base = super().descriptor()
        base.update({"kind": "files", "roots": [{"id": item.get("id"), "name": item.get("name"), "path": item.get("path")} for item in self.roots]})
        return base

    def _load_roots(self) -> list[dict[str, Any]]:
        roots: list[dict[str, Any]] = []
        for item in self.roots:
            if not isinstance(item, dict):
                continue
            root_id = str(item.get("id", "")).strip()
            path = Path(str(item.get("path", "")).strip()).expanduser()
            if not root_id or not str(path):
                continue
            if not path.is_absolute():
                path = self.settings.base_dir / path
            patterns_raw = item.get("patterns", ["**/*.py", "**/*.md", "**/*.json", "**/*.txt", "**/*.yaml", "**/*.yml"])
            patterns = [str(pattern).strip() for pattern in patterns_raw if str(pattern).strip()] if isinstance(patterns_raw, list) else ["**/*"]
            roots.append(
                {
                    "id": root_id,
                    "name": str(item.get("name", root_id)).strip() or root_id,
                    "path": path,
                    "patterns": patterns,
                }
            )
        return roots

    def _coerce_safe_root(self, path: Path) -> Path:
        candidate = path.expanduser().resolve()
        if self.settings.files_allow_outside_project:
            return candidate
        project_root = self.settings.base_dir.resolve()
        if project_root not in candidate.parents and candidate != project_root:
            raise ValueError("Pfad ausserhalb Projekt ist blockiert.")
        return candidate

    def _iter_files(self, root: dict[str, Any]) -> list[Path]:
        base = self._coerce_safe_root(root["path"])
        if not base.exists() or not base.is_dir():
            return []
        files: list[Path] = []
        seen: set[Path] = set()
        for pattern in root["patterns"]:
            for path in base.glob(pattern):
                resolved = path.resolve()
                if not resolved.is_file() or resolved in seen:
                    continue
                seen.add(resolved)
                files.append(resolved)
        files.sort()
        return files

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[: self.settings.files_read_max_chars]
        except Exception:
            return ""

    def _resolve_root(self, root_id: str) -> dict[str, Any] | None:
        for root in self._load_roots():
            if root["id"] == root_id:
                return root
        return None

    def _score_file(self, query_tokens: list[str], relative_path: str, text: str) -> float:
        haystack_path = relative_path.lower()
        haystack_text = text.lower()
        score = 0.0
        for token in query_tokens:
            if token in haystack_path:
                score += 4.0
            if token in Path(relative_path).name.lower():
                score += 5.0
            if token in haystack_text:
                score += 1.5
        return score

    def _search(self, query: str, root_id: str = "", limit: int = 0) -> MCPResult:
        roots = self._load_roots()
        if not roots:
            return MCPResult(False, self.mcp_id, "search", "Keine File-Roots konfiguriert.", {}, "no_roots")
        query = query.strip()
        if not query:
            return MCPResult(False, self.mcp_id, "search", "Files-MCP braucht query.", {}, "missing_query")
        safe_limit = max(1, min(self.settings.files_search_max_results, int(limit or self.settings.files_search_max_results)))
        cache_key = hashlib.sha1(f"{query}|{root_id}|{safe_limit}".encode("utf-8")).hexdigest()
        cached = self.search_cache.get(cache_key)
        if cached is not None:
            return MCPResult(True, self.mcp_id, "search", "Dateisuche aus Cache geliefert.", cached)

        query_tokens = _tokenize(query)
        results: list[dict[str, Any]] = []
        active_roots = [root for root in roots if not root_id or root["id"] == root_id]
        for root in active_roots:
            base = self._coerce_safe_root(root["path"])
            for path in self._iter_files(root):
                relative = str(path.relative_to(base))
                text = self._read_text(path)
                score = self._score_file(query_tokens, relative, text)
                if score <= 0:
                    continue
                line_preview = next((line.strip() for line in text.splitlines() if any(token in line.lower() for token in query_tokens)), "")
                results.append(
                    {
                        "root_id": root["id"],
                        "root_name": root["name"],
                        "path": relative,
                        "absolute_path": str(path),
                        "score": round(score, 2),
                        "preview": line_preview[:280],
                    }
                )
        results.sort(key=lambda item: (item["score"], item["path"]), reverse=True)
        payload = {"results": results[:safe_limit], "roots_considered": len(active_roots), "cache_hit": False}
        self.search_cache.set(cache_key, payload)
        return MCPResult(True, self.mcp_id, "search", f"{len(payload['results'])} Dateitreffer gefunden.", payload)

    def _list(self, root_id: str = "", prefix: str = "", limit: int = 50) -> MCPResult:
        roots = self._load_roots()
        if not roots:
            return MCPResult(False, self.mcp_id, "list", "Keine File-Roots konfiguriert.", {}, "no_roots")
        safe_limit = max(1, min(200, int(limit)))
        rows: list[dict[str, Any]] = []
        for root in roots:
            if root_id and root["id"] != root_id:
                continue
            base = self._coerce_safe_root(root["path"])
            normalized_prefix = prefix.strip().lower().lstrip("/")
            for path in self._iter_files(root):
                relative = str(path.relative_to(base))
                if normalized_prefix and not relative.lower().startswith(normalized_prefix):
                    continue
                rows.append({"root_id": root["id"], "root_name": root["name"], "path": relative, "absolute_path": str(path)})
                if len(rows) >= safe_limit:
                    break
            if len(rows) >= safe_limit:
                break
        return MCPResult(True, self.mcp_id, "list", f"{len(rows)} Dateien gelistet.", {"results": rows})

    def _read(self, root_id: str, relative_path: str) -> MCPResult:
        root = self._resolve_root(root_id)
        if root is None:
            return MCPResult(False, self.mcp_id, "read", "root_id fehlt oder ist ungueltig.", {}, "invalid_root")
        base = self._coerce_safe_root(root["path"])
        normalized = relative_path.strip().lstrip("/")
        if not normalized:
            return MCPResult(False, self.mcp_id, "read", "path fehlt.", {}, "missing_path")
        candidate = (base / normalized).resolve()
        if base not in candidate.parents and candidate != base:
            return MCPResult(False, self.mcp_id, "read", "Pfad ausserhalb der freigegebenen Root.", {}, "path_blocked")
        if not candidate.exists() or not candidate.is_file():
            return MCPResult(False, self.mcp_id, "read", "Datei nicht gefunden.", {}, "file_not_found")
        text = self._read_text(candidate)
        return MCPResult(
            True,
            self.mcp_id,
            "read",
            "Datei gelesen.",
            {
                "root_id": root["id"],
                "root_name": root["name"],
                "path": normalized,
                "absolute_path": str(candidate),
                "content": text,
                "truncated": len(text) >= self.settings.files_read_max_chars,
            },
        )

    def health(self) -> MCPResult:
        cached = self.health_cache.get("health")
        if cached is not None:
            return MCPResult(**cached)
        roots = self._load_roots()
        rows: list[dict[str, Any]] = []
        ready = True
        for root in roots:
            base = self._coerce_safe_root(root["path"])
            exists = base.exists() and base.is_dir()
            file_count = len(self._iter_files(root)) if exists else 0
            rows.append({"id": root["id"], "name": root["name"], "path": str(base), "exists": exists, "file_count": file_count})
            ready = ready and exists
        result = MCPResult(
            success=ready and bool(roots),
            mcp_id=self.mcp_id,
            action="health",
            message="File-Roots bereit." if ready and roots else "Mindestens eine File-Root fehlt.",
            data={"roots": rows, "roots_count": len(rows)},
            error="" if ready and roots else "roots_unavailable",
        )
        self.health_cache.set("health", result.as_dict())
        return result

    def stats(self) -> MCPResult:
        health = self.health()
        roots = health.data.get("roots", []) if isinstance(health.data, dict) else []
        total_files = sum(int(item.get("file_count", 0)) for item in roots if isinstance(item, dict))
        return MCPResult(True, self.mcp_id, "stats", "File-Statistik bereit.", {"roots": roots, "files_total": total_files})

    def execute(self, action: str, payload: dict[str, Any]) -> MCPResult:
        normalized = action.strip().lower() or "search"
        if normalized == "health":
            return self.health()
        if normalized == "stats":
            return self.stats()
        if normalized == "search":
            return self._search(str(payload.get("query", "")), str(payload.get("root_id", "")), int(payload.get("limit", 0) or 0))
        if normalized == "list":
            return self._list(str(payload.get("root_id", "")), str(payload.get("prefix", "")), int(payload.get("limit", 50) or 50))
        if normalized == "read":
            return self._read(str(payload.get("root_id", "")), str(payload.get("path", "")))
        return MCPResult(False, self.mcp_id, normalized, "Unbekannte Files-MCP action.", {}, "invalid_action")


class NetBoxMCP(BaseMCP):
    OBJECT_PATHS = {
        "devices": "/api/dcim/devices/",
        "sites": "/api/dcim/sites/",
        "racks": "/api/dcim/racks/",
        "interfaces": "/api/dcim/interfaces/",
        "ip-addresses": "/api/ipam/ip-addresses/",
        "prefixes": "/api/ipam/prefixes/",
        "vlans": "/api/ipam/vlans/",
        "tenants": "/api/tenancy/tenants/",
        "virtual-machines": "/api/virtualization/virtual-machines/",
        "clusters": "/api/virtualization/clusters/",
    }
    OBJECT_ALIASES = {
        "device": "devices",
        "devices": "devices",
        "site": "sites",
        "sites": "sites",
        "rack": "racks",
        "racks": "racks",
        "interface": "interfaces",
        "interfaces": "interfaces",
        "ip": "ip-addresses",
        "ip-addresses": "ip-addresses",
        "ip_addresses": "ip-addresses",
        "prefix": "prefixes",
        "prefixes": "prefixes",
        "vlan": "vlans",
        "vlans": "vlans",
        "tenant": "tenants",
        "tenants": "tenants",
        "vm": "virtual-machines",
        "virtual-machines": "virtual-machines",
        "cluster": "clusters",
        "clusters": "clusters",
    }

    def __init__(
        self,
        *,
        mcp_id: str,
        label: str,
        description: str,
        settings: Settings,
        base_url: str = "",
        token: str = "",
        token_env: str = "",
        cache_ttl_seconds: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(mcp_id, label, description)
        self.settings = settings
        self.base_url = self._normalize_base_url(base_url or settings.netbox_base_url)
        self.token = token.strip() or settings.netbox_token
        self.token_env = token_env.strip() or settings.netbox_token_env
        self.cache_ttl_seconds = max(5, int(cache_ttl_seconds or settings.netbox_cache_ttl_seconds))
        self.timeout_seconds = max(3.0, float(timeout_seconds or settings.netbox_timeout_seconds))
        self.cache: TTLCache[dict[str, Any]] = TTLCache(self.cache_ttl_seconds, 256)
        self.health_cache: TTLCache[dict[str, Any]] = TTLCache(max(10, min(self.cache_ttl_seconds, 60)), 8)
        self.catalog_cache: TTLCache[dict[str, Any]] = TTLCache(max(30, min(self.cache_ttl_seconds * 4, 300)), 8)
        timeout = httpx.Timeout(
            connect=max(3.0, self.timeout_seconds),
            read=max(3.0, self.timeout_seconds),
            write=max(3.0, self.timeout_seconds),
            pool=10.0,
        )
        limits = httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=60.0)
        self._client = httpx.Client(timeout=timeout, limits=limits)

    def descriptor(self) -> dict[str, Any]:
        base = super().descriptor()
        base.update({"kind": "netbox", "base_url": self.base_url})
        return base

    def _resolve_token(self, payload: dict[str, Any]) -> str:
        if str(payload.get("token", "")).strip():
            return str(payload.get("token", "")).strip()
        token_env = str(payload.get("token_env", "")).strip() or self.token_env
        if token_env:
            return os.getenv(token_env, "").strip()
        return self.token

    def _auth_headers(self, token: str) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Token {token}"
        return headers

    def _health_timeout(self) -> httpx.Timeout:
        # Keep UI health checks responsive even if NetBox is slow or unreachable.
        connect_timeout = min(max(2.0, self.timeout_seconds), 3.0)
        total_timeout = min(max(3.0, self.timeout_seconds), 4.0)
        return httpx.Timeout(connect=connect_timeout, read=total_timeout, write=total_timeout, pool=connect_timeout)

    def _normalize_base_url(self, raw_url: str) -> str:
        url = raw_url.strip().rstrip("/")
        if url.lower().endswith("/api"):
            return url[:-4]
        return url

    def _token_scope(self, token: str) -> str:
        return hashlib.sha1(token.encode("utf-8")).hexdigest()[:12] if token else "anonymous"

    def _catalog_cache_key(self, base_url: str, token: str) -> str:
        return f"{self._normalize_base_url(base_url)}::{self._token_scope(token)}"

    def _extract_api_path(self, url: str) -> str:
        candidate = str(url or "").strip()
        if not candidate:
            return ""
        parsed = urlsplit(candidate)
        path = parsed.path or candidate
        if "/api/" not in path:
            return ""
        path = path[path.index("/api/") :]
        return path.rstrip("/") + "/"

    def _looks_like_link_map(self, payload: Any) -> bool:
        if not isinstance(payload, dict) or not payload:
            return False
        values = [value for value in payload.values() if isinstance(value, str)]
        if not values:
            return False
        return all("/api/" in value for value in values)

    def _register_endpoint(self, api_path: str, paths: dict[str, str], aliases: dict[str, str]) -> None:
        normalized = api_path.rstrip("/") + "/"
        segments = [segment for segment in normalized.split("/") if segment]
        if "api" not in segments:
            return
        api_index = segments.index("api")
        resource_segments = segments[api_index + 1 :]
        if len(resource_segments) < 2:
            return
        short_key = resource_segments[-1]
        canonical_key = ".".join(resource_segments)
        key = short_key if short_key not in paths else canonical_key
        paths[key] = normalized

        alias_candidates = {
            key,
            canonical_key,
            "-".join(resource_segments),
            "_".join(resource_segments),
            normalized,
            normalized.rstrip("/"),
            short_key,
        }
        if len(resource_segments) >= 2:
            alias_candidates.add(f"{resource_segments[-2]}.{resource_segments[-1]}")
            alias_candidates.add(f"{resource_segments[-2]}-{resource_segments[-1]}")
        if short_key.endswith("s") and len(short_key) > 3:
            alias_candidates.add(short_key[:-1])

        for alias in alias_candidates:
            aliases.setdefault(alias.lower(), key)

    def _fetch_discovery_payload(self, url: str, token: str) -> dict[str, Any] | None:
        try:
            response = self._client.get(url, headers=self._auth_headers(token))
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _dynamic_catalog(self, base_url: str, token: str) -> dict[str, Any]:
        cache_key = self._catalog_cache_key(base_url, token)
        cached = self.catalog_cache.get(cache_key)
        if cached is not None:
            return cached

        paths: dict[str, str] = dict(self.OBJECT_PATHS)
        aliases: dict[str, str] = {alias.lower(): value for alias, value in self.OBJECT_ALIASES.items()}
        for key in self.OBJECT_PATHS:
            aliases.setdefault(key.lower(), key)

        api_root_url = self.api_root_url(base_url)
        visited_urls: set[str] = set()
        queue: list[tuple[str, int]] = [(api_root_url, 0)] if api_root_url else []

        while queue:
            current_url, depth = queue.pop(0)
            if not current_url or current_url in visited_urls or depth > 2:
                continue
            visited_urls.add(current_url)

            payload = self._fetch_discovery_payload(current_url, token)
            if payload is None or not self._looks_like_link_map(payload):
                continue

            for value in payload.values():
                if not isinstance(value, str):
                    continue
                api_path = self._extract_api_path(value)
                if not api_path:
                    continue
                self._register_endpoint(api_path, paths, aliases)
                if value not in visited_urls:
                    queue.append((value, depth + 1))

        catalog = {"paths": paths, "aliases": aliases}
        self.catalog_cache.set(cache_key, catalog)
        return catalog

    def _resolve_object_type(self, raw: str, *, base_url: str = "", token: str = "") -> str:
        candidate = str(raw or "").strip()
        if not candidate:
            return ""
        catalog = self._dynamic_catalog(base_url or self.base_url, token)
        alias_key = candidate.lower()
        if alias_key in catalog["aliases"]:
            return str(catalog["aliases"][alias_key])
        direct_path = self._extract_api_path(candidate)
        if direct_path:
            for key, value in catalog["paths"].items():
                if value.rstrip("/") == direct_path.rstrip("/"):
                    return str(key)
        return ""

    def available_object_types(self, base_url: str = "", token: str = "") -> list[str]:
        catalog = self._dynamic_catalog(base_url or self.base_url, token)
        return sorted(catalog["paths"].keys())

    def object_endpoint_url(self, object_type: str, base_url: str | None = None) -> str:
        normalized_type = self._resolve_object_type(object_type, base_url=base_url or self.base_url)
        root = self._normalize_base_url(base_url or self.base_url)
        catalog = self._dynamic_catalog(base_url or self.base_url, "")
        path = catalog["paths"].get(normalized_type, "")
        return f"{root}{path}" if root and path else ""

    def api_root_url(self, base_url: str | None = None) -> str:
        root = self._normalize_base_url(base_url or self.base_url)
        return f"{root}/api/" if root else ""

    def schema_candidate_urls(self, base_url: str | None = None) -> list[str]:
        root = self._normalize_base_url(base_url or self.base_url)
        if not root:
            return []
        return [
            f"{root}/api/schema/?format=openapi",
            f"{root}/api/schema/",
            f"{root}/api/docs/?format=openapi",
            f"{root}/api/docs/?format=json",
        ]

    def _fetch_schema_document(self, base_url: str, token: str) -> tuple[dict[str, Any] | None, str, str]:
        last_error = ""
        for candidate_url in self.schema_candidate_urls(base_url):
            try:
                response = self._client.get(candidate_url, headers=self._auth_headers(token))
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload, candidate_url, ""
            except Exception as exc:
                last_error = str(exc)
                continue
        return None, "", last_error

    def _schema_parameters_for_path(self, schema_payload: dict[str, Any], endpoint_path: str) -> list[dict[str, Any]]:
        parameters = (
            schema_payload.get("paths", {})
            .get(endpoint_path, {})
            .get("get", {})
            .get("parameters", [])
        )
        rows: list[dict[str, Any]] = []
        if isinstance(parameters, list):
            for item in parameters:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "name": str(item.get("name", "")),
                        "in": str(item.get("in", "")),
                        "required": bool(item.get("required", False)),
                        "description": str(item.get("description", "")).strip(),
                    }
                )
        return rows

    def _options_metadata(self, endpoint_url: str, token: str) -> dict[str, Any]:
        try:
            response = self._client.options(endpoint_url, headers=self._auth_headers(token))
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
        return {}

    def explore_fields(
        self,
        *,
        object_type: str,
        query: str = "",
        sample_limit: int = 1,
        base_url: str = "",
        token: str = "",
        token_env: str = "",
    ) -> MCPResult:
        normalized_type = self._resolve_object_type(object_type, base_url=base_url or self.base_url, token=token)
        if not normalized_type:
            return MCPResult(False, self.mcp_id, "explore_fields", "object_type fehlt oder ist ungueltig.", {}, "invalid_object_type")
        effective_base_url = self._normalize_base_url(base_url or self.base_url)
        effective_token = token.strip() if token.strip() else self._resolve_token({"token_env": token_env} if token_env else {})
        catalog = self._dynamic_catalog(effective_base_url, effective_token)
        endpoint_path = catalog["paths"][normalized_type]
        endpoint_url = f"{effective_base_url}{endpoint_path}"
        params: dict[str, Any] = {"limit": max(1, min(10, int(sample_limit)))}
        if query.strip():
            params["q"] = query.strip()
        try:
            response = self._client.get(endpoint_url, headers=self._auth_headers(effective_token), params=params)
            response.raise_for_status()
            payload_json = response.json()
            rows = payload_json.get("results", []) if isinstance(payload_json, dict) else []
            sample_object = rows[0] if isinstance(rows, list) and rows else {}
            sample_keys = sorted(sample_object.keys()) if isinstance(sample_object, dict) else []
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return MCPResult(False, self.mcp_id, "explore_fields", f"NetBox HTTP Fehler {status}.", {}, f"http_status_{status}")
        except httpx.RequestError as exc:
            return MCPResult(False, self.mcp_id, "explore_fields", f"NetBox Netzwerkfehler: {exc}", {}, "request_error")

        schema_filters: list[dict[str, Any]] = []
        schema_payload, schema_url, schema_error = self._fetch_schema_document(effective_base_url, effective_token)
        if schema_payload is not None:
            schema_filters = self._schema_parameters_for_path(schema_payload, endpoint_path)

        options_metadata = self._options_metadata(endpoint_url, effective_token)

        return MCPResult(
            True,
            self.mcp_id,
            "explore_fields",
            "NetBox Feld-Explorer bereit.",
            {
                "object_type": normalized_type,
                "endpoint_path": endpoint_path,
                "endpoint_url": endpoint_url,
                "query": query.strip(),
                "sample_limit": params["limit"],
                "sample_keys": sample_keys,
                "sample_object": sample_object if isinstance(sample_object, dict) else {},
                "available_filters": schema_filters,
                "schema_url": schema_url,
                "schema_error": schema_error,
                "options_metadata": options_metadata,
            },
        )

    def execute(self, action: str, payload: dict[str, Any]) -> MCPResult:
        normalized = action.strip().lower()
        aliases = {
            "devices": "devices",
            "device": "devices",
            "ip-addresses": "ip-addresses",
            "ip_addresses": "ip-addresses",
            "ip": "ip-addresses",
            "get_objects": "get_objects",
            "get_object_by_id": "get_object_by_id",
            "get_changelogs": "get_changelogs",
            "health": "health",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized == "health":
            return self.health()
        base_url = self._normalize_base_url(str(payload.get("base_url", "")).strip() or self.base_url)
        token = self._resolve_token(payload)
        if not base_url:
            return MCPResult(False, self.mcp_id, normalized, "NetBox base_url fehlt.", {}, "missing_base_url")
        catalog = self._dynamic_catalog(base_url, token)

        params = payload.get("filters", payload.get("params", {}))
        if not isinstance(params, dict):
            params = {}
        request_url = ""
        if normalized in {"devices", "ip-addresses"}:
            request_url = f"{base_url}{catalog['paths'][normalized]}"
        elif normalized == "get_objects":
            object_type = self._resolve_object_type(str(payload.get("object_type", params.get("object_type", ""))), base_url=base_url, token=token)
            if not object_type:
                return MCPResult(False, self.mcp_id, normalized, "object_type fehlt oder ist ungueltig.", {}, "invalid_object_type")
            request_url = f"{base_url}{catalog['paths'][object_type]}"
            limit = payload.get("limit", params.get("limit", 50))
            try:
                params["limit"] = max(1, min(200, int(limit)))
            except (TypeError, ValueError):
                params["limit"] = 50
        elif normalized == "get_object_by_id":
            object_type = self._resolve_object_type(str(payload.get("object_type", params.get("object_type", ""))), base_url=base_url, token=token)
            if not object_type:
                return MCPResult(False, self.mcp_id, normalized, "object_type fehlt oder ist ungueltig.", {}, "invalid_object_type")
            object_id = payload.get("id", payload.get("object_id"))
            try:
                numeric_id = int(object_id)
            except (TypeError, ValueError):
                return MCPResult(False, self.mcp_id, normalized, "Numerische id fehlt.", {}, "invalid_id")
            params = {}
            request_url = f"{base_url}{catalog['paths'][object_type]}{numeric_id}/"
        elif normalized == "get_changelogs":
            request_url = f"{base_url}/api/core/object-changes/"
            limit = payload.get("limit", params.get("limit", 100))
            try:
                params["limit"] = max(1, min(200, int(limit)))
            except (TypeError, ValueError):
                params["limit"] = 100
        else:
            return MCPResult(False, self.mcp_id, normalized, "Unbekannte NetBox action.", {}, "invalid_action")

        token_scope = self._token_scope(token)
        cache_key = hashlib.sha1(
            json.dumps(
                {"url": request_url, "params": params, "action": normalized, "auth": token_scope},
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        cached = self.cache.get(cache_key)
        if cached is not None:
            return MCPResult(True, self.mcp_id, normalized, "NetBox Antwort aus Cache geliefert.", {**cached, "cache_hit": True})

        try:
            response = self._client.get(request_url, headers=self._auth_headers(token), params=params)
            response.raise_for_status()
            payload_json = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            message = f"NetBox HTTP Fehler {status}."
            if status in {401, 403} and not token:
                message = f"NetBox HTTP Fehler {status}. Der Endpoint ist erreichbar, lehnt anonyme Requests aber ab."
            return MCPResult(False, self.mcp_id, normalized, message, {}, f"http_status_{status}")
        except httpx.RequestError as exc:
            return MCPResult(False, self.mcp_id, normalized, f"NetBox Netzwerkfehler: {exc}", {}, "request_error")

        result: dict[str, Any]
        if normalized == "get_object_by_id":
            result = {"object": payload_json}
        else:
            count = payload_json.get("count") if isinstance(payload_json, dict) else None
            rows = payload_json.get("results", []) if isinstance(payload_json, dict) else []
            result = {"count": count, "results": rows if isinstance(rows, list) else []}
        self.cache.set(cache_key, result)
        return MCPResult(True, self.mcp_id, normalized, "NetBox Antwort erfolgreich.", {**result, "cache_hit": False})

    def health(self) -> MCPResult:
        if not self.base_url:
            return MCPResult(False, self.mcp_id, "health", "NetBox base_url fehlt.", {}, "missing_base_url")
        cached = self.health_cache.get("health")
        if cached is not None:
            return MCPResult(**cached)
        token = self.token or (os.getenv(self.token_env, "").strip() if self.token_env else "")
        probe_url = f"{self._normalize_base_url(self.base_url)}/api/status/"
        if not token:
            logger.info("NetBox health probe without token: %s", probe_url)
        try:
            response = self._client.get(probe_url, headers=self._auth_headers(token), timeout=self._health_timeout())
            response.raise_for_status()
        except httpx.RequestError as exc:
            result = MCPResult(False, self.mcp_id, "health", f"NetBox nicht erreichbar: {exc}", {"base_url": self.base_url}, "request_error")
            self.health_cache.set("health", result.as_dict())
            return result
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            if status in {401, 403}:
                message = "NetBox Host erreichbar, Status-Endpoint ist jedoch geschuetzt."
                if token:
                    message = f"NetBox Host erreichbar, aber Status-Endpoint antwortet mit HTTP {status}."
                result = MCPResult(
                    True,
                    self.mcp_id,
                    "health",
                    message,
                    {
                        "base_url": self.base_url,
                        "probe_url": probe_url,
                        "status_code": status,
                        "auth_mode": "token" if token else "anonymous",
                        "status_endpoint_protected": True,
                    },
                )
                self.health_cache.set("health", result.as_dict())
                return result
            result = MCPResult(
                False,
                self.mcp_id,
                "health",
                f"NetBox HTTP Fehler {status}.",
                {"base_url": self.base_url, "probe_url": probe_url, "status_code": status},
                f"http_status_{status}",
            )
            self.health_cache.set("health", result.as_dict())
            return result
        result = MCPResult(
            True,
            self.mcp_id,
            "health",
            "NetBox erreichbar.",
            {"base_url": self.base_url, "probe_url": probe_url, "auth_mode": "token" if token else "anonymous"},
        )
        self.health_cache.set("health", result.as_dict())
        return result

    def close(self) -> None:
        self._client.close()


class RemoteHttpMCP(BaseMCP):
    def __init__(
        self,
        *,
        mcp_id: str,
        label: str,
        description: str,
        base_url: str,
        execute_path: str = "/execute",
        health_path: str = "/health",
        bearer_token: str = "",
        bearer_token_env: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(mcp_id, label, description)
        self.base_url = str(base_url).strip().rstrip("/")
        self.execute_path = str(execute_path or "/execute").strip() or "/execute"
        self.health_path = str(health_path or "/health").strip() or "/health"
        self.bearer_token = bearer_token.strip()
        self.bearer_token_env = bearer_token_env.strip()
        self.timeout_seconds = max(3.0, float(timeout_seconds))
        timeout = httpx.Timeout(connect=max(3.0, self.timeout_seconds), read=max(3.0, self.timeout_seconds), write=max(3.0, self.timeout_seconds), pool=10.0)
        self._client = httpx.Client(timeout=timeout)

    def descriptor(self) -> dict[str, Any]:
        base = super().descriptor()
        base.update({"kind": "remote_http", "base_url": self.base_url, "execute_path": self.execute_path, "health_path": self.health_path})
        return base

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = self.bearer_token or (os.getenv(self.bearer_token_env, "").strip() if self.bearer_token_env else "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def health(self) -> MCPResult:
        if not self.base_url:
            return MCPResult(False, self.mcp_id, "health", "Remote MCP base_url fehlt.", {}, "missing_base_url")
        try:
            response = self._client.get(f"{self.base_url}{self.health_path}", headers=self._headers())
            response.raise_for_status()
            payload = response.json() if response.content else {}
            return MCPResult(True, self.mcp_id, "health", "Remote MCP erreichbar.", {"response": payload, "base_url": self.base_url})
        except Exception as exc:
            return MCPResult(False, self.mcp_id, "health", f"Remote MCP nicht erreichbar: {exc}", {"base_url": self.base_url}, "request_error")

    def handshake(self) -> MCPResult:
        if not self.base_url:
            return MCPResult(False, self.mcp_id, "handshake", "Remote MCP base_url fehlt.", {}, "missing_base_url")
        try:
            health_result = self.health()
            capabilities: dict[str, Any] = {}
            health_payload = health_result.data.get("response", {}) if isinstance(health_result.data, dict) else {}
            if isinstance(health_payload, dict):
                for key in ("capabilities", "actions", "version", "service", "name"):
                    if key in health_payload:
                        capabilities[key] = health_payload[key]
            probe_payload = {
                "action": "handshake",
                "payload": {
                    "client": "woddi-ai-control",
                    "client_version": "0.1.0",
                    "mcp_id": self.mcp_id,
                },
            }
            response = self._client.post(
                f"{self.base_url}{self.execute_path}",
                headers=self._headers(),
                json=probe_payload,
            )
            response.raise_for_status()
            raw = response.json() if response.content else {}
            if isinstance(raw, dict):
                capabilities["handshake_response"] = raw
                if isinstance(raw.get("data"), dict):
                    for key in ("capabilities", "actions", "version", "service", "name"):
                        if key in raw["data"]:
                            capabilities[key] = raw["data"][key]
            return MCPResult(
                True,
                self.mcp_id,
                "handshake",
                "Remote MCP Handshake erfolgreich.",
                {
                    "base_url": self.base_url,
                    "execute_url": f"{self.base_url}{self.execute_path}",
                    "health_url": f"{self.base_url}{self.health_path}",
                    "capabilities": capabilities,
                },
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return MCPResult(False, self.mcp_id, "handshake", f"Remote MCP Handshake HTTP Fehler {status}.", {}, f"http_status_{status}")
        except Exception as exc:
            return MCPResult(False, self.mcp_id, "handshake", f"Remote MCP Handshake Fehler: {exc}", {}, "request_error")

    def execute(self, action: str, payload: dict[str, Any]) -> MCPResult:
        normalized = action.strip().lower() or "health"
        if normalized == "health":
            return self.health()
        if normalized == "handshake":
            return self.handshake()
        if not self.base_url:
            return MCPResult(False, self.mcp_id, normalized, "Remote MCP base_url fehlt.", {}, "missing_base_url")
        try:
            response = self._client.post(
                f"{self.base_url}{self.execute_path}",
                headers=self._headers(),
                json={"action": normalized, "payload": payload},
            )
            response.raise_for_status()
            raw = response.json() if response.content else {}
            if isinstance(raw, dict) and {"success", "message", "data"}.issubset(raw.keys()):
                return MCPResult(
                    bool(raw.get("success")),
                    self.mcp_id,
                    normalized,
                    str(raw.get("message", "")),
                    raw.get("data", {}) if isinstance(raw.get("data"), dict) else {},
                    str(raw.get("error", "")),
                )
            return MCPResult(True, self.mcp_id, normalized, "Remote MCP Antwort erfolgreich.", {"response": raw if isinstance(raw, dict) else {"raw": raw}})
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return MCPResult(False, self.mcp_id, normalized, f"Remote MCP HTTP Fehler {status}.", {}, f"http_status_{status}")
        except Exception as exc:
            return MCPResult(False, self.mcp_id, normalized, f"Remote MCP Fehler: {exc}", {}, "request_error")

    def close(self) -> None:
        self._client.close()


class MCPRegistry:
    def __init__(self, *, settings: Settings, llm: LlmClient) -> None:
        self.settings = settings
        self.llm = llm
        self._mcps: dict[str, BaseMCP] = {}
        self._load_from_config()

    def _load_from_config(self) -> None:
        if not self.settings.mcps_config_path.exists():
            return
        raw = json.loads(self.settings.mcps_config_path.read_text(encoding="utf-8"))
        items = raw.get("mcps", []) if isinstance(raw, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            mcp_id = str(item.get("id", "")).strip()
            if not mcp_id or not bool(item.get("enabled", True)):
                continue
            kind = str(item.get("kind", "")).strip().lower()
            label = str(item.get("name", mcp_id)).strip() or mcp_id
            description = str(item.get("description", f"MCP {label}")).strip() or f"MCP {label}"
            if kind == "docs":
                source_path = Path(str(item.get("path", "")).strip()).expanduser()
                if not source_path.is_absolute():
                    source_path = self.settings.base_dir / source_path
                patterns_raw = item.get("patterns", ["**/*.md", "**/*.txt", "**/*.adoc", "**/*.rst", "**/*.html"])
                patterns = [str(pattern).strip() for pattern in patterns_raw if str(pattern).strip()] if isinstance(patterns_raw, list) else ["**/*.md"]
                self._mcps[mcp_id] = DocumentationMCP(
                    source_id=mcp_id,
                    label=label,
                    source_path=source_path,
                    patterns=patterns,
                    llm=self.llm,
                    settings=self.settings,
                )
                continue
            if kind == "files":
                roots_raw = item.get("roots", [])
                roots = list(roots_raw) if isinstance(roots_raw, list) else []
                self._mcps[mcp_id] = FilesMCP(
                    mcp_id=mcp_id,
                    label=label,
                    description=description,
                    settings=self.settings,
                    roots=roots,
                )
                continue
            if kind == "netbox":
                self._mcps[mcp_id] = NetBoxMCP(
                    mcp_id=mcp_id,
                    label=label,
                    description=description,
                    settings=self.settings,
                    base_url=str(item.get("base_url", "")).strip(),
                    token=str(item.get("token", "")).strip(),
                    token_env=str(item.get("token_env", "")).strip(),
                    cache_ttl_seconds=int(item.get("cache_ttl_seconds", 0) or 0),
                    timeout_seconds=float(item.get("timeout_seconds", 0) or 0),
                )
                continue
            if kind == "remote_http":
                self._mcps[mcp_id] = RemoteHttpMCP(
                    mcp_id=mcp_id,
                    label=label,
                    description=description,
                    base_url=str(item.get("base_url", "")).strip(),
                    execute_path=str(item.get("execute_path", "/execute")).strip() or "/execute",
                    health_path=str(item.get("health_path", "/health")).strip() or "/health",
                    bearer_token=str(item.get("bearer_token", "")).strip(),
                    bearer_token_env=str(item.get("bearer_token_env", "")).strip(),
                    timeout_seconds=float(item.get("timeout_seconds", 15) or 15),
                )
                continue

    def list(self) -> list[dict[str, Any]]:
        return [mcp.descriptor() for mcp in self._mcps.values()]

    def ids(self) -> list[str]:
        return list(self._mcps.keys())

    def execute(self, mcp_id: str, action: str, payload: dict[str, Any]) -> MCPResult:
        mcp = self._mcps.get(mcp_id)
        if mcp is None:
            return MCPResult(False, mcp_id, action, "MCP nicht gefunden.", {}, "mcp_not_found")
        return mcp.execute(action, payload)

    def docs_only(self) -> list[DocumentationMCP]:
        return [mcp for mcp in self._mcps.values() if isinstance(mcp, DocumentationMCP)]

    def files_only(self) -> list[FilesMCP]:
        return [mcp for mcp in self._mcps.values() if isinstance(mcp, FilesMCP)]

    def netbox_only(self) -> list[NetBoxMCP]:
        return [mcp for mcp in self._mcps.values() if isinstance(mcp, NetBoxMCP)]

    def get_documentation_mcp(self, mcp_id: str) -> DocumentationMCP | None:
        mcp = self._mcps.get(mcp_id)
        return mcp if isinstance(mcp, DocumentationMCP) else None

    def get_netbox_mcp(self) -> NetBoxMCP | None:
        for mcp in self._mcps.values():
            if isinstance(mcp, NetBoxMCP):
                return mcp
        return None

    def get_files_mcp(self) -> FilesMCP | None:
        for mcp in self._mcps.values():
            if isinstance(mcp, FilesMCP):
                return mcp
        return None

    def close(self) -> None:
        for mcp in self._mcps.values():
            close_fn = getattr(mcp, "close", None)
            if callable(close_fn):
                close_fn()
