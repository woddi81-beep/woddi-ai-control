from __future__ import annotations

import argparse
import io
import json
import logging
import os
import queue
import shutil
import sys
import subprocess
import threading
import time
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .chat import MonoAssistant
from .config import configure_logging, load_runtime_config, load_settings, save_runtime_config
from .llm import LlmClient
from .mcp import MCPRegistry
from .metrics import PerformanceTracker
from .security import AuthManager, AuthSession


settings = load_settings()
configure_logging(settings)
logger = logging.getLogger(settings.app_name)
runtime_lock = threading.RLock()
llm: LlmClient | None = None
registry: MCPRegistry | None = None
assistant: MonoAssistant | None = None
performance = PerformanceTracker()
auth_manager = AuthManager(settings.users_config_path)
SESSION_COOKIE = "woddi_ai_control_session"


def _read_release_info() -> dict[str, str]:
    release = "dev"
    commit = ""
    version_path = settings.base_dir / "VERSION"
    if version_path.exists():
        release = version_path.read_text(encoding="utf-8", errors="replace").strip() or release
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(settings.base_dir), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        commit = ""
    return {"release": release, "commit": commit}


RELEASE_INFO = _read_release_info()


def reload_runtime() -> None:
    global settings, llm, registry, assistant, logger
    with runtime_lock:
        old_llm = llm
        old_registry = registry
        settings = load_settings()
        configure_logging(settings)
        logger = logging.getLogger(settings.app_name)
        llm = LlmClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            fallback_model=settings.llm_fallback_model,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
        registry = MCPRegistry(settings=settings, llm=llm)
        assistant = MonoAssistant(settings=settings, llm=llm, registry=registry)
        auth_manager.users_path = settings.users_config_path
    if old_registry is not None:
        old_registry.close()
    if old_llm is not None:
        old_llm.close()


reload_runtime()

app = FastAPI(title=settings.app_name, version="0.1.0")

WEB_DIR = settings.base_dir / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None


class MCPRequest(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfigRequest(BaseModel):
    config: dict[str, Any]


class LoginRequest(BaseModel):
    username: str
    password: str


class LlmProbeRequest(BaseModel):
    base_url: str | None = None
    timeout_seconds: float | None = Field(default=None, ge=3.0, le=900.0)


class NetBoxProbeRequest(BaseModel):
    base_url: str | None = None
    token: str | None = None
    token_env: str | None = None
    timeout_seconds: float | None = Field(default=None, ge=3.0, le=120.0)


class NetBoxExplorerRequest(BaseModel):
    object_type: str = Field(min_length=1, max_length=64)
    query: str = Field(default="", max_length=256)
    sample_limit: int = Field(default=1, ge=1, le=10)


class DocsSourcesRequest(BaseModel):
    sources: list[dict[str, Any]]


class FilesSourcesRequest(BaseModel):
    sources: list[dict[str, Any]]


class McpsConfigRequest(BaseModel):
    mcps: list[dict[str, Any]]


class UsersConfigRequest(BaseModel):
    groups: list[dict[str, Any]] = Field(default_factory=list)
    users: list[dict[str, Any]] = Field(default_factory=list)


class SystemPromptRequest(BaseModel):
    prompt: str


class PersonaRequest(BaseModel):
    content: str


class ControlRequest(BaseModel):
    delay_seconds: float = Field(default=0.8, ge=0.2, le=5.0)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {_json_dumps(payload)}\n\n"


def _state() -> tuple[Any, Any, Any, Any]:
    with runtime_lock:
        return settings, llm, registry, assistant


def _session_from_request(request: Request) -> AuthSession | None:
    return auth_manager.get_session(request.cookies.get(SESSION_COOKIE, ""))


def _require_session(request: Request) -> AuthSession:
    session = _session_from_request(request)
    if session is None:
        raise HTTPException(status_code=401, detail="auth_required")
    return session


def _require_admin(request: Request) -> AuthSession:
    session = _require_session(request)
    if not session.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return session


def _session_can_access_mcp(session: AuthSession, mcp_id: str) -> bool:
    if session.is_admin:
        return True
    return "*" in session.allowed_mcp_ids or mcp_id in session.allowed_mcp_ids


def _filter_mcps_for_session(items: list[dict[str, Any]], session: AuthSession) -> list[dict[str, Any]]:
    if session.is_admin:
        return items
    return [item for item in items if _session_can_access_mcp(session, str(item.get("id", "")))]


def _sanitize_mcp_descriptor_for_user(item: dict[str, Any], *, is_admin: bool) -> dict[str, Any]:
    if is_admin:
        return item
    sanitized = {}
    blocked_keys = {"source_path", "index_path", "index_meta_path", "absolute_path", "base_url", "roots_path"}
    for key, value in item.items():
        if key in blocked_keys:
            continue
        sanitized[key] = value
    return sanitized


def _record_metric(category: str, name: str, started_at: float, *, ok: bool = True, data: dict[str, Any] | None = None) -> None:
    performance.record(category, name, (time.perf_counter() - started_at) * 1000.0, ok=ok, data=data)


def _service_log_path(current_settings: Any) -> Path:
    return current_settings.log_file.parent / f"{current_settings.app_name}-service.log"


def _mask_secret(value: str) -> str:
    secret = (value or "").strip()
    if not secret:
        return ""
    if len(secret) <= 6:
        return "*" * len(secret)
    return f"{secret[:3]}{'*' * (len(secret) - 6)}{secret[-3:]}"


def _resolve_netbox_probe_input(body: NetBoxProbeRequest | None = None) -> tuple[str, str, float]:
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    requested = body or NetBoxProbeRequest()
    base_url = _normalize_netbox_base_url(requested.base_url or current_settings.netbox_base_url)
    token_env = (requested.token_env or current_settings.netbox_token_env).strip()
    token = (requested.token or "").strip()
    if not token and token_env:
        token = os.getenv(token_env, "").strip()
    if not token:
        token = current_settings.netbox_token.strip()
    timeout_seconds = float(requested.timeout_seconds or current_settings.netbox_timeout_seconds)
    return base_url, token, timeout_seconds


def _build_netbox_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=max(3.0, timeout_seconds),
        read=max(3.0, min(timeout_seconds, 10.0)),
        write=max(3.0, timeout_seconds),
        pool=10.0,
    )


def _netbox_probe_payload(base_url: str, token: str, timeout_seconds: float) -> dict[str, Any]:
    normalized_base = base_url[:-4] if base_url.lower().endswith("/api") else base_url
    probe_url = f"{normalized_base}/api/status/" if normalized_base else ""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    started_at = time.perf_counter()
    timeout = _build_netbox_timeout(timeout_seconds)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(probe_url, headers=headers)
        response.raise_for_status()
        payload = {
            "success": True,
            "message": "NetBox erreichbar.",
            "status_code": response.status_code,
            "base_url": base_url,
            "probe_url": probe_url,
            "auth_mode": "token" if token else "anonymous",
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status in {401, 403}:
            payload = {
                "success": True,
                "message": f"NetBox erreichbar, Status-Endpoint antwortet mit HTTP {status}.",
                "status_code": status,
                "base_url": base_url,
                "probe_url": probe_url,
                "auth_mode": "token" if token else "anonymous",
                "status_endpoint_protected": True,
            }
        else:
            raise HTTPException(status_code=400, detail=f"NetBox Probe fehlgeschlagen: HTTP {status}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NetBox Probe fehlgeschlagen: {exc}") from exc
    return {
        **payload,
        "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
    }


def _netbox_headers(token: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def _tail_text(path: Path, max_lines: int) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    if max_lines <= 0:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _docs_sources_payload(current_settings: Any) -> dict[str, Any]:
    config = _mcps_config_payload(current_settings)
    sources = []
    for item in config.get("mcps", []):
        if not isinstance(item, dict) or str(item.get("kind", "")).strip().lower() != "docs":
            continue
        sources.append(
            {
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "path": str(item.get("path", "")),
                "patterns": item.get("patterns", []),
            }
        )
    return {"sources": sources}


def _write_docs_sources(current_settings: Any, sources: list[dict[str, Any]]) -> None:
    config = _mcps_config_payload(current_settings)
    others = [item for item in config.get("mcps", []) if isinstance(item, dict) and str(item.get("kind", "")).strip().lower() != "docs"]
    docs_mcps = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        docs_mcps.append(
            {
                "id": str(item.get("id", "")).strip(),
                "name": str(item.get("name", "")).strip() or str(item.get("id", "")).strip(),
                "description": f"Lokale Dokumentationsquelle {str(item.get('name', item.get('id', ''))).strip()}",
                "kind": "docs",
                "enabled": True,
                "path": str(item.get("path", "")).strip(),
                "patterns": item.get("patterns", []),
            }
        )
    _write_mcps_config(current_settings, others + docs_mcps)


def _files_sources_payload(current_settings: Any) -> dict[str, Any]:
    config = _mcps_config_payload(current_settings)
    for item in config.get("mcps", []):
        if not isinstance(item, dict) or str(item.get("kind", "")).strip().lower() != "files":
            continue
        roots = item.get("roots", []) if isinstance(item.get("roots"), list) else []
        return {"sources": roots}
    return {"sources": []}


def _write_files_sources(current_settings: Any, sources: list[dict[str, Any]]) -> None:
    config = _mcps_config_payload(current_settings)
    mcps: list[dict[str, Any]] = []
    updated = False
    for item in config.get("mcps", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("kind", "")).strip().lower() == "files" and not updated:
            clone = json.loads(json.dumps(item))
            clone["roots"] = sources
            mcps.append(clone)
            updated = True
        else:
            mcps.append(item)
    if not updated:
        mcps.append(
            {
                "id": "files-main",
                "name": "Workspace Files",
                "description": "Dateibasiertes MCP",
                "kind": "files",
                "enabled": True,
                "roots": sources,
            }
        )
    _write_mcps_config(current_settings, mcps)


def _mcps_config_payload(current_settings: Any) -> dict[str, Any]:
    raw = {"mcps": []}
    if current_settings.mcps_config_path.exists():
        try:
            data = json.loads(current_settings.mcps_config_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                raw = data
        except Exception:
            raw = {"mcps": []}
    return raw


def _write_mcps_config(current_settings: Any, mcps: list[dict[str, Any]]) -> None:
    current_settings.mcps_config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mcps": mcps}
    current_settings.mcps_config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _users_config_payload(current_settings: Any) -> dict[str, Any]:
    raw = {"groups": [], "users": []}
    if current_settings.users_config_path.exists():
        try:
            data = json.loads(current_settings.users_config_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                raw = data
        except Exception:
            raw = {"groups": [], "users": []}
    return raw


def _write_users_config(current_settings: Any, groups: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    current_settings.users_config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"groups": groups, "users": users}
    current_settings.users_config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _persona_index(current_settings: Any) -> list[dict[str, Any]]:
    current_settings.personas_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(current_settings.personas_dir.glob("*.md")):
        items.append(
            {
                "id": path.stem,
                "name": path.stem.replace("-", " ").replace("_", " ").strip().title() or path.stem,
                "path": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return items


def _persona_path(current_settings: Any, persona_id: str) -> Path:
    safe_id = "".join(character for character in persona_id.strip().lower() if character.isalnum() or character in {"-", "_"})
    if not safe_id:
        raise HTTPException(status_code=400, detail="ungueltige_persona_id")
    return current_settings.personas_dir / f"{safe_id}.md"


def _docs_catalog(current_settings: Any) -> list[dict[str, Any]]:
    candidates = [current_settings.base_dir / "README.md", *sorted((current_settings.base_dir / "docs").glob("*.md"))]
    items: list[dict[str, Any]] = []
    for path in candidates:
        if not path.exists():
            continue
        items.append(
            {
                "id": path.stem.lower(),
                "title": path.stem.replace("_", " ").title(),
                "path": str(path),
                "content": path.read_text(encoding="utf-8", errors="replace"),
            }
        )
    return items


def _session_system_prompt(current_settings: Any, session: AuthSession) -> str:
    persona_id = session.persona_id or "default"
    try:
        path = _persona_path(current_settings, persona_id)
    except HTTPException:
        path = current_settings.system_prompt_path
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace").strip()
    if current_settings.system_prompt_path.exists():
        return current_settings.system_prompt_path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _normalize_llm_base_url(raw_url: str) -> str:
    candidate = str(raw_url or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlsplit(candidate)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if not netloc and parsed.path:
        netloc = parsed.path
        path = ""
    if not netloc:
        return candidate.rstrip("/")
    normalized_path = path or "/v1"
    if normalized_path == "/":
        normalized_path = "/v1"
    return urlunsplit((scheme, netloc, normalized_path, "", "")).rstrip("/")


def _normalize_netbox_base_url(raw_url: str) -> str:
    candidate = str(raw_url or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if not netloc and parsed.path:
        netloc = parsed.path
        path = ""
    if not netloc:
        return candidate.rstrip("/")
    normalized_path = path or "/api"
    if normalized_path == "/":
        normalized_path = "/api"
    return urlunsplit((scheme, netloc, normalized_path, "", "")).rstrip("/")


def _normalized_runtime_payload(config: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(config))
    llm_section = payload.get("llm")
    if isinstance(llm_section, dict):
        base_url = llm_section.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            llm_section["base_url"] = _normalize_llm_base_url(base_url)
    netbox_section = payload.get("netbox")
    if isinstance(netbox_section, dict):
        base_url = netbox_section.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            netbox_section["base_url"] = _normalize_netbox_base_url(base_url)
    return payload


def _llm_models_url(base_url: str) -> str:
    normalized = _normalize_llm_base_url(base_url)
    if normalized.endswith("/v1"):
        return f"{normalized}/models"
    return f"{normalized.rstrip('/')}/models"


def _validate_zip_member(member_name: str) -> None:
    normalized = member_name.replace("\\", "/").strip()
    if not normalized:
        return
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=400, detail=f"Ungueltiger ZIP-Pfad: {member_name}")


def _pick_extracted_root(temp_dir: Path) -> Path:
    entries = sorted(temp_dir.iterdir(), key=lambda item: item.name)
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return temp_dir


def _install_docs_archive(target_dir: Path, archive: UploadFile) -> dict[str, Any]:
    filename = (archive.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Es werden nur ZIP-Dateien unterstuetzt.")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{target_dir.name}-upload-", dir=str(target_dir.parent)))
    backup_dir: Path | None = None
    file_count = 0
    try:
        archive.file.seek(0)
        try:
            with zipfile.ZipFile(archive.file) as zip_file:
                members = zip_file.infolist()
                if not members:
                    raise HTTPException(status_code=400, detail="ZIP-Datei ist leer.")
                for member in members:
                    _validate_zip_member(member.filename)
                zip_file.extractall(temp_root)
                file_count = len([member for member in members if not member.is_dir()])
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="ZIP-Datei ist ungueltig.") from exc

        extracted_root = _pick_extracted_root(temp_root)
        replacement_dir = temp_root if extracted_root == temp_root else extracted_root
        if target_dir.exists():
            backup_dir = target_dir.parent / f".{target_dir.name}.backup-{int(time.time() * 1000)}"
            target_dir.rename(backup_dir)
        replacement_dir.rename(target_dir)
        if backup_dir is not None and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        return {"filename": filename, "files_extracted": file_count, "target_path": str(target_dir)}
    except HTTPException:
        if backup_dir is not None and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        raise
    except Exception as exc:
        if backup_dir is not None and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"ZIP-Import fehlgeschlagen: {exc}") from exc


def _netbox_summary(current_settings: Any) -> dict[str, Any]:
    token_env = current_settings.netbox_token_env.strip()
    token_env_value = os.getenv(token_env, "").strip() if token_env else ""
    token_value = current_settings.netbox_token.strip()
    if token_value:
        auth_mode = "static_token"
    elif token_env and token_env_value:
        auth_mode = "token_env"
    else:
        auth_mode = "anonymous"
    base_url = current_settings.netbox_base_url.rstrip("/")
    normalized_base = base_url[:-4] if base_url.lower().endswith("/api") else base_url
    probe_url = f"{normalized_base}/api/status/" if normalized_base else ""
    return {
        "base_url": current_settings.netbox_base_url,
        "auth_mode": auth_mode,
        "token_present": bool(token_value or token_env_value),
        "token_env": token_env,
        "status_probe_url": probe_url,
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_session(request)
    current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    visible_descriptors = _filter_mcps_for_session(current_registry.list(), session)
    descriptors = {item["id"]: _sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in visible_descriptors}
    mcp_health = []
    for item in descriptors.values():
        result = current_registry.execute(item["id"], "health", {})
        mcp_health.append({**item, **result.as_dict()})
    payload = {
        "status": "ok",
        "app": current_settings.app_name,
        "release": RELEASE_INFO,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "llm_model": current_settings.llm_model,
        "mcps": mcp_health,
    }
    if session.is_admin:
        payload["llm_base_url"] = current_settings.llm_base_url
        payload["mcps_config_path"] = str(current_settings.mcps_config_path)
    _record_metric("endpoint", "/health", started_at, data={"mcp_count": len(mcp_health)})
    return payload


@app.get("/api/config")
def api_config(request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_session(request)
    current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    visible_mcps = _filter_mcps_for_session(current_registry.list(), session)
    payload = {
        "app_name": current_settings.app_name,
        "release": RELEASE_INFO,
        "llm": {"model": current_settings.llm_model},
        "mcps": visible_mcps,
        "personas": _persona_index(current_settings),
        "defaults": {
            "docs_top_k": current_settings.docs_top_k,
            "context_max_chars": current_settings.context_max_chars,
        },
        "viewer": {
            "username": session.username,
            "display_name": session.display_name,
            "role": session.role,
            "is_admin": session.is_admin,
            "groups": list(session.groups),
            "persona_id": session.persona_id,
            "allowed_mcp_ids": list(session.allowed_mcp_ids),
        },
    }
    if session.is_admin:
        payload["llm"] = {
            "base_url": current_settings.llm_base_url,
            "model": current_settings.llm_model,
            "fallback_model": current_settings.llm_fallback_model,
            "cache_ttl_seconds": current_settings.llm_cache_ttl_seconds,
            "cache_max_entries": current_settings.llm_cache_max_entries,
        }
        payload["docs"] = {
            "allow_outside_project": current_settings.docs_allow_outside_project,
            "source_scan_cache_ttl_seconds": current_settings.docs_source_scan_cache_ttl_seconds,
            "health_cache_ttl_seconds": current_settings.docs_health_cache_ttl_seconds,
            "search_cache_ttl_seconds": current_settings.docs_search_cache_ttl_seconds,
            "answer_cache_ttl_seconds": current_settings.docs_answer_cache_ttl_seconds,
        }
        payload["files"] = {
            "allow_outside_project": current_settings.files_allow_outside_project,
            "search_cache_ttl_seconds": current_settings.files_search_cache_ttl_seconds,
            "read_max_chars": current_settings.files_read_max_chars,
            "search_max_results": current_settings.files_search_max_results,
        }
        payload["netbox"] = _netbox_summary(current_settings)
        payload["paths"] = {
            "runtime_config": str(current_settings.runtime_config_path),
            "mcps_config": str(current_settings.mcps_config_path),
            "passwd": str(current_settings.users_config_path),
            "personas_dir": str(current_settings.personas_dir),
            "docs_cache_dir": str(current_settings.docs_cache_dir),
            "system_prompt": str(current_settings.system_prompt_path),
            "log_file": str(current_settings.log_file),
            "service_log_file": str(_service_log_path(current_settings)),
        }
    _record_metric("endpoint", "/api/config", started_at, data={"mcp_count": len(payload["mcps"])})
    return payload


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    session = _require_session(request)
    current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    return {
        "authenticated": True,
        "username": session.username,
        "display_name": session.display_name,
        "role": session.role,
        "is_admin": session.is_admin,
        "groups": list(session.groups),
        "persona_id": session.persona_id,
        "allowed_mcp_ids": list(session.allowed_mcp_ids),
        "mcps": _filter_mcps_for_session(current_registry.list(), session),
        "personas": _persona_index(current_settings),
        "app_name": current_settings.app_name,
    }


@app.post("/api/auth/login")
def auth_login(body: LoginRequest, response: Response) -> dict[str, Any]:
    user = auth_manager.verify_credentials(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    session = auth_manager.create_session(user)
    response.set_cookie(SESSION_COOKIE, session.token, httponly=True, samesite="lax", max_age=auth_manager.session_ttl_seconds, path="/")
    return {"success": True, "username": session.username, "role": session.role, "is_admin": session.is_admin}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    auth_manager.clear_session(request.cookies.get(SESSION_COOKIE, ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"success": True}


@app.get("/api/mcps")
def list_mcps(request: Request) -> dict[str, Any]:
    session = _require_session(request)
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    return {"items": _filter_mcps_for_session(current_registry.list(), session)}


@app.get("/api/docs")
def list_docs(request: Request) -> dict[str, Any]:
    _require_session(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"items": _docs_catalog(current_settings)}


@app.get("/api/personas")
def list_personas(request: Request) -> dict[str, Any]:
    session = _require_session(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    items = _persona_index(current_settings)
    if session.is_admin:
        return {"items": items}
    return {"items": [item for item in items if item["id"] == session.persona_id]}


@app.post("/api/mcp/{mcp_id}")
def execute_mcp(mcp_id: str, body: MCPRequest, request: Request) -> JSONResponse:
    started_at = time.perf_counter()
    session = _require_session(request)
    if not _session_can_access_mcp(session, mcp_id):
        raise HTTPException(status_code=403, detail="mcp_not_allowed")
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    result = current_registry.execute(mcp_id, body.action, body.payload)
    status = 200 if result.success else 400
    _record_metric(
        "mcp",
        f"{mcp_id}:{body.action}",
        started_at,
        ok=result.success,
        data={"mcp_id": mcp_id, "action": body.action, "http_status": status},
    )
    return JSONResponse(result.as_dict(), status_code=status)


@app.get("/api/admin/runtime")
def get_runtime(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {
        "config": load_runtime_config(current_settings.runtime_config_path),
        "path": str(current_settings.runtime_config_path),
    }


@app.put("/api/admin/runtime")
def put_runtime(body: RuntimeConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    normalized_config = _normalized_runtime_payload(body.config)
    save_runtime_config(normalized_config, current_settings.runtime_config_path)
    reload_runtime()
    _record_metric("endpoint", "/api/admin/runtime:put", started_at)
    return {"success": True, "path": str(current_settings.runtime_config_path)}


@app.post("/api/admin/llm-probe")
def probe_llm(body: LlmProbeRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    base_url = _normalize_llm_base_url(body.base_url or current_settings.llm_base_url)
    timeout_seconds = float(body.timeout_seconds or current_settings.llm_timeout_seconds)
    timeout = httpx.Timeout(
        connect=max(3.0, timeout_seconds),
        read=max(5.0, min(timeout_seconds, 30.0)),
        write=max(3.0, timeout_seconds),
        pool=10.0,
    )
    probe_url = _llm_models_url(base_url)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(probe_url)
        response.raise_for_status()
        payload = response.json() if response.content else {}
        items = payload.get("data", []) if isinstance(payload, dict) else []
        model_ids = []
        if isinstance(items, list):
            for item in items[:12]:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    model_ids.append(item["id"])
        result = {
            "success": True,
            "base_url": base_url,
            "probe_url": probe_url,
            "status_code": response.status_code,
            "models": model_ids,
            "models_count": len(model_ids),
            "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
        }
        _record_metric("endpoint", "/api/admin/llm-probe", started_at, data={"status_code": response.status_code, "base_url": base_url})
        return result
    except Exception as exc:
        _record_metric("endpoint", "/api/admin/llm-probe", started_at, ok=False, data={"base_url": base_url, "reason": str(exc)})
        raise HTTPException(status_code=400, detail=f"LLM Probe fehlgeschlagen: {exc}") from exc


@app.post("/api/admin/netbox-probe")
def probe_netbox(body: NetBoxProbeRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    base_url, token, timeout_seconds = _resolve_netbox_probe_input(body)
    try:
        payload = _netbox_probe_payload(base_url, token, timeout_seconds)
    except Exception as exc:
        _record_metric("endpoint", "/api/admin/netbox-probe", started_at, ok=False, data={"base_url": base_url, "reason": str(exc)})
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"NetBox Probe fehlgeschlagen: {exc}") from exc
    response = payload
    _record_metric("endpoint", "/api/admin/netbox-probe", started_at, ok=bool(payload["success"]), data={"base_url": base_url})
    return response


@app.post("/api/admin/netbox-explorer")
def explore_netbox_fields(body: NetBoxExplorerRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    netbox_mcp = current_registry.get_netbox_mcp()
    if netbox_mcp is None:
        raise HTTPException(status_code=404, detail="NetBox MCP nicht gefunden.")
    result = netbox_mcp.explore_fields(
        object_type=body.object_type,
        query=body.query,
        sample_limit=body.sample_limit,
    )
    _record_metric(
        "endpoint",
        "/api/admin/netbox-explorer",
        started_at,
        ok=result.success,
        data={"object_type": body.object_type, "query": body.query},
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result.as_dict()


@app.post("/api/admin/netbox-bundle")
def download_netbox_bundle(body: NetBoxExplorerRequest, request: Request) -> StreamingResponse:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    netbox_mcp = current_registry.get_netbox_mcp()
    if netbox_mcp is None:
        raise HTTPException(status_code=404, detail="NetBox MCP nicht gefunden.")

    base_url, token, timeout_seconds = _resolve_netbox_probe_input(None)
    object_types = netbox_mcp.available_object_types(base_url=base_url, token=token)
    selected_query = body.query.strip()
    selected_type = body.object_type
    sample_limit = max(1, min(10, body.sample_limit))

    bundle: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_name": current_settings.app_name,
        "netbox": {
            "base_url": base_url,
            "token_present": bool(token),
            "token_masked": _mask_secret(token),
            "token_env": current_settings.netbox_token_env,
            "timeout_seconds": timeout_seconds,
            "cache_ttl_seconds": current_settings.netbox_cache_ttl_seconds,
        },
        "selected_request": {
            "object_type": selected_type,
            "query": selected_query,
            "sample_limit": sample_limit,
        },
        "available_object_types": object_types,
        "sample_payloads": {
            object_type: {
                "action": "get_objects",
                "payload": {
                    "object_type": object_type,
                    "filters": {"q": selected_query or f"<{object_type}-query>", "limit": 5},
                },
            }
            for object_type in object_types
        },
    }

    try:
        bundle["probe"] = _netbox_probe_payload(base_url, token, timeout_seconds)
    except Exception as exc:
        bundle["probe_error"] = str(exc)

    schema_payload: dict[str, Any] | None = None
    schema_url = ""
    api_root_payload: dict[str, Any] | None = None
    api_root_error = ""
    api_root_url = netbox_mcp.api_root_url(base_url)
    if api_root_url:
        try:
            with httpx.Client(timeout=_build_netbox_timeout(timeout_seconds)) as client:
                response = client.get(api_root_url, headers=_netbox_headers(token))
            response.raise_for_status()
            raw_root = response.json()
            api_root_payload = raw_root if isinstance(raw_root, dict) else {"raw": raw_root}
        except Exception as exc:
            api_root_error = str(exc)

    for candidate_url in netbox_mcp.schema_candidate_urls(base_url):
        try:
            with httpx.Client(timeout=_build_netbox_timeout(timeout_seconds)) as client:
                response = client.get(candidate_url, headers=_netbox_headers(token))
            response.raise_for_status()
            raw_schema = response.json()
            schema_payload = raw_schema if isinstance(raw_schema, dict) else {"raw": raw_schema}
            schema_url = candidate_url
            break
        except Exception as exc:
            bundle.setdefault("schema_attempts", []).append({"url": candidate_url, "error": str(exc)})

    bundle["api_root_url"] = api_root_url
    if api_root_payload is not None:
        bundle["api_root_keys"] = sorted(api_root_payload.keys())
    if api_root_error:
        bundle["api_root_error"] = api_root_error
    if schema_url:
        bundle["schema_url"] = schema_url
    elif "schema_attempts" in bundle:
        bundle["schema_error"] = "Keine der bekannten Schema-URLs lieferte JSON."

    explorers: dict[str, Any] = {}
    for object_type in object_types:
        result = netbox_mcp.explore_fields(
            object_type=object_type,
            query=selected_query if object_type == selected_type else "",
            sample_limit=1 if object_type != selected_type else sample_limit,
            base_url=base_url,
            token=token,
        )
        explorers[object_type] = result.as_dict()

    selected_result = explorers.get(selected_type)
    if selected_result is None:
        result = netbox_mcp.explore_fields(
            object_type=selected_type,
            query=selected_query,
            sample_limit=sample_limit,
            base_url=base_url,
            token=token,
        )
        selected_result = result.as_dict()

    archive = io.BytesIO()
    filename = f"netbox-mcp-bundle-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt",
            (
                "NetBox MCP Diagnose-Bundle\n"
                "\n"
                "Enthaelt die aktuelle NetBox-MCP-Konfiguration (ohne Klartext-Token),\n"
                "Probe-Daten, das OpenAPI-Schema der NetBox, Explorer-Snapshots pro Objekt-Typ\n"
                "und Beispiel-Payloads fuer passende MCP-Calls.\n"
            ),
        )
        zf.writestr("bundle/meta.json", json.dumps(bundle, ensure_ascii=False, indent=2))
        zf.writestr("bundle/selected_explorer.json", json.dumps(selected_result, ensure_ascii=False, indent=2))
        zf.writestr("bundle/explorers.json", json.dumps(explorers, ensure_ascii=False, indent=2))
        if schema_payload is not None:
            zf.writestr("bundle/netbox_openapi_schema.json", json.dumps(schema_payload, ensure_ascii=False, indent=2))
        if api_root_payload is not None:
            zf.writestr("bundle/netbox_api_root.json", json.dumps(api_root_payload, ensure_ascii=False, indent=2))

    archive.seek(0)
    _record_metric(
        "endpoint",
        "/api/admin/netbox-bundle",
        started_at,
        ok=True,
        data={"object_type": selected_type, "query": selected_query, "object_types": len(object_types)},
    )
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/admin/docs-sources")
def get_docs_sources(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"config": _docs_sources_payload(current_settings), "path": str(current_settings.docs_sources_path)}


@app.put("/api/admin/docs-sources")
def put_docs_sources(body: DocsSourcesRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _write_docs_sources(current_settings, body.sources)
    reload_runtime()
    _record_metric("endpoint", "/api/admin/docs-sources:put", started_at, data={"sources": len(body.sources)})
    return {"success": True, "path": str(current_settings.docs_sources_path)}


@app.get("/api/admin/files-sources")
def get_files_sources(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"config": _files_sources_payload(current_settings), "path": str(current_settings.files_sources_path)}


@app.put("/api/admin/files-sources")
def put_files_sources(body: FilesSourcesRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _write_files_sources(current_settings, body.sources)
    reload_runtime()
    _record_metric("endpoint", "/api/admin/files-sources:put", started_at, data={"sources": len(body.sources)})
    return {"success": True, "path": str(current_settings.files_sources_path)}


@app.get("/api/admin/mcps")
def get_mcps_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"config": _mcps_config_payload(current_settings), "path": str(current_settings.mcps_config_path)}


@app.put("/api/admin/mcps")
def put_mcps_config(body: McpsConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _write_mcps_config(current_settings, body.mcps)
    reload_runtime()
    _record_metric("endpoint", "/api/admin/mcps:put", started_at, data={"mcps": len(body.mcps)})
    return {"success": True, "path": str(current_settings.mcps_config_path)}


@app.post("/api/admin/mcps/{mcp_id}/handshake")
def handshake_mcp(mcp_id: str, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    result = current_registry.execute(mcp_id, "handshake", {})
    _record_metric("endpoint", "/api/admin/mcps/handshake", started_at, ok=result.success, data={"mcp_id": mcp_id})
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result.as_dict()


@app.get("/api/admin/users")
def get_users_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"config": _users_config_payload(current_settings), "path": str(current_settings.users_config_path)}


@app.put("/api/admin/users")
def put_users_config(body: UsersConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _write_users_config(current_settings, body.groups, body.users)
    reload_runtime()
    _record_metric("endpoint", "/api/admin/users:put", started_at, data={"users": len(body.users)})
    return {"success": True, "path": str(current_settings.users_config_path)}


@app.get("/api/admin/personas")
def get_personas(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    items = []
    for item in _persona_index(current_settings):
        content = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
        items.append({**item, "content": content})
    return {"items": items, "dir": str(current_settings.personas_dir)}


@app.put("/api/admin/personas/{persona_id}")
def put_persona(persona_id: str, body: PersonaRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    path = _persona_path(current_settings, persona_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content.rstrip() + "\n", encoding="utf-8")
    if path == current_settings.system_prompt_path:
        reload_runtime()
    _record_metric("endpoint", "/api/admin/personas:put", started_at, data={"persona_id": persona_id})
    return {"success": True, "id": persona_id, "path": str(path)}


@app.post("/api/admin/docs-sources/{source_id}/upload")
def upload_docs_archive(
    source_id: str,
    request: Request,
    archive: UploadFile = File(...),
    reindex: bool = Form(default=True),
) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    docs_mcp = current_registry.get_documentation_mcp(source_id)
    if docs_mcp is None:
        raise HTTPException(status_code=404, detail="Docs-Quelle nicht gefunden.")
    try:
        target_dir = docs_mcp.resolve_source_path()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    upload_meta = _install_docs_archive(target_dir, archive)
    docs_mcp.clear_runtime_caches()
    reindex_result = docs_mcp.reindex(force=True) if reindex else None
    payload = {
        "success": True,
        "source_id": source_id,
        "upload": upload_meta,
        "reindex": reindex_result.as_dict() if reindex_result is not None else None,
    }
    _record_metric(
        "endpoint",
        "/api/admin/docs-sources/upload",
        started_at,
        ok=payload["success"],
        data={"source_id": source_id, "reindex": reindex, "files_extracted": upload_meta.get("files_extracted", 0)},
    )
    return payload


@app.get("/api/admin/system-prompt")
def get_system_prompt(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    prompt = ""
    if current_settings.system_prompt_path.exists():
        prompt = current_settings.system_prompt_path.read_text(encoding="utf-8", errors="replace")
    return {"prompt": prompt, "path": str(current_settings.system_prompt_path)}


@app.put("/api/admin/system-prompt")
def put_system_prompt(body: SystemPromptRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    current_settings.system_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    current_settings.system_prompt_path.write_text(body.prompt.rstrip() + "\n", encoding="utf-8")
    reload_runtime()
    _record_metric("endpoint", "/api/admin/system-prompt:put", started_at)
    return {"success": True, "path": str(current_settings.system_prompt_path)}


@app.get("/api/admin/logs")
def get_logs(request: Request, file: str = "service", lines: int = 160) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    candidates = {
        "app": current_settings.log_file,
        "service": _service_log_path(current_settings),
    }
    selected = candidates.get(file, candidates["service"])
    try:
        normalized_lines = max(20, min(600, int(lines)))
    except (TypeError, ValueError):
        normalized_lines = 160
    files = []
    for key, path in candidates.items():
        files.append(
            {
                "id": key,
                "name": path.name,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
        )
    payload = {
        "selected": file if file in candidates else "service",
        "lines": normalized_lines,
        "content": _tail_text(selected, normalized_lines),
        "files": files,
    }
    _record_metric("endpoint", "/api/admin/logs", started_at, data={"file": payload["selected"], "lines": normalized_lines})
    return payload


@app.get("/api/admin/performance")
def get_performance(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return performance.snapshot()


@app.post("/api/admin/reload")
def admin_reload(request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    reload_runtime()
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _record_metric("endpoint", "/api/admin/reload", started_at)
    return {"success": True, "app_name": current_settings.app_name}


def _schedule_execv(delay_seconds: float) -> None:
    def worker() -> None:
        time.sleep(delay_seconds)
        current_settings, _current_llm, _current_registry, _current_assistant = _state()
        args = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", current_settings.host, "--port", str(current_settings.port)]
        os.execv(sys.executable, args)

    threading.Thread(target=worker, daemon=True).start()


def _schedule_exit(delay_seconds: float) -> None:
    def worker() -> None:
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=worker, daemon=True).start()


@app.post("/api/admin/control/restart")
def control_restart(body: ControlRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    _schedule_execv(body.delay_seconds)
    _record_metric("endpoint", "/api/admin/control/restart", started_at, data={"delay_seconds": body.delay_seconds})
    return {"success": True, "action": "restart", "delay_seconds": body.delay_seconds}


@app.post("/api/admin/control/shutdown")
def control_shutdown(body: ControlRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin(request)
    _schedule_exit(body.delay_seconds)
    _record_metric("endpoint", "/api/admin/control/shutdown", started_at, data={"delay_seconds": body.delay_seconds})
    return {"success": True, "action": "shutdown", "delay_seconds": body.delay_seconds}


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_session(request)
    current_settings, _current_llm, _current_registry, current_assistant = _state()
    assert current_assistant is not None
    metadata = dict(body.metadata or {})
    raw_selected = metadata.get("selected_mcp_ids", [])
    if not isinstance(raw_selected, list):
        raw_selected = []
    metadata["selected_mcp_ids"] = [str(mcp_id).strip() for mcp_id in raw_selected if _session_can_access_mcp(session, str(mcp_id).strip())]
    metadata["system_prompt"] = _session_system_prompt(current_settings, session)
    try:
        result = current_assistant.chat(message=body.message, session_id=body.session_id, metadata=metadata)
    except RuntimeError as exc:
        _record_metric("chat", "sync_error", started_at, ok=False, data={"reason": str(exc), "input_chars": len(body.message)})
        if str(exc) == "rate_limited":
            raise HTTPException(status_code=429, detail="rate_limited") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    perf_payload = dict(result.get("perf", {}))
    perf_payload["request_total_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
    perf_payload["transport"] = "sync"
    _record_metric("chat", str(result.get("route", "sync")), started_at, data=perf_payload)
    return {
        **result,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    session = _require_session(request)

    def generate() -> Any:
        q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        _current_settings, _current_llm, _current_registry, current_assistant = _state()
        assert current_assistant is not None
        started_at = time.perf_counter()
        first_chunk_at: list[float | None] = [None]

        def on_chunk(piece: str) -> None:
            if first_chunk_at[0] is None:
                first_chunk_at[0] = time.perf_counter()
            q.put(("chunk", {"text": piece}))

        def worker() -> None:
            try:
                metadata = dict(body.metadata or {})
                current_settings, _inner_llm, _inner_registry, _inner_assistant = _state()
                raw_selected = metadata.get("selected_mcp_ids", [])
                if not isinstance(raw_selected, list):
                    raw_selected = []
                metadata["selected_mcp_ids"] = [str(mcp_id).strip() for mcp_id in raw_selected if _session_can_access_mcp(session, str(mcp_id).strip())]
                metadata["system_prompt"] = _session_system_prompt(current_settings, session)
                result = current_assistant.chat(
                    message=body.message,
                    session_id=body.session_id,
                    metadata=metadata,
                    on_chunk=on_chunk,
                )
                perf_payload = dict(result.get("perf", {}))
                perf_payload["transport"] = "stream"
                perf_payload["request_total_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
                perf_payload["first_token_ms"] = (
                    round((first_chunk_at[0] - started_at) * 1000.0, 2) if first_chunk_at[0] is not None else 0.0
                )
                _record_metric("chat", str(result.get("route", "stream")), started_at, data=perf_payload)
                q.put(("meta", {"session_id": result["session_id"], "route": result["route"], "citations": result["citations"]}))
                q.put(("done", result))
            except RuntimeError as exc:
                logger.warning("chat_stream runtime error: %s", exc)
                _record_metric(
                    "chat",
                    "stream_error",
                    started_at,
                    ok=False,
                    data={"reason": str(exc), "input_chars": len(body.message)},
                )
                if str(exc) == "rate_limited":
                    q.put(("error", {"message": "Rate limit erreicht."}))
                else:
                    q.put(("error", {"message": str(exc)}))
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception("chat_stream failed")
                _record_metric(
                    "chat",
                    "stream_error",
                    started_at,
                    ok=False,
                    data={"reason": str(exc), "input_chars": len(body.message)},
                )
                q.put(("error", {"message": str(exc)}))
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        yield _event("start", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
        while True:
            try:
                item = q.get(timeout=5.0)
            except queue.Empty:
                yield _event("ping", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
                continue
            if item is None:
                break
            event_name, payload = item
            yield _event(event_name, payload)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.on_event("shutdown")
def shutdown_event() -> None:
    _current_settings, current_llm, current_registry, _current_assistant = _state()
    if current_registry is not None:
        current_registry.close()
    if current_llm is not None:
        current_llm.close()


def run() -> None:
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    uvicorn.run("app.main:app", host=current_settings.host, port=current_settings.port, reload=False)


def main() -> None:
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    parser = argparse.ArgumentParser(description="woddi-ai-control")
    parser.add_argument("--host", default=current_settings.host)
    parser.add_argument("--port", type=int, default=current_settings.port)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
