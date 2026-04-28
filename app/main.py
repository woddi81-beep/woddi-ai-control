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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .chat import MonoAssistant
from .config import configure_logging, load_runtime_config, load_settings
from .llm import LlmClient
from .mcp import MCPRegistry, RemoteHttpMCP
from .metrics import PerformanceTracker
from .security import AuthManager, AuthSession, hash_password, password_hash_is_modern, password_hash_scheme


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


class SetupBootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    password_confirm: str = Field(min_length=12, max_length=256)


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


class McpGuideProbeRequest(BaseModel):
    action: str = Field(min_length=1, max_length=32)
    draft: dict[str, Any]


class UsersConfigRequest(BaseModel):
    groups: list[dict[str, Any]] = Field(default_factory=list)
    users: list[dict[str, Any]] = Field(default_factory=list)


class SystemPromptRequest(BaseModel):
    prompt: str


class PersonaRequest(BaseModel):
    content: str


class ChangeOwnPasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    new_password_confirm: str = Field(min_length=12, max_length=256)


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)
    new_password_confirm: str = Field(min_length=12, max_length=256)


class ControlRequest(BaseModel):
    delay_seconds: float = Field(default=0.8, ge=0.2, le=5.0)


class RuntimeAppConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    log_level: str | None = Field(default=None, min_length=1, max_length=32)
    log_file: str | None = Field(default=None, min_length=1, max_length=400)


class RuntimeLlmConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = Field(default=None, min_length=1, max_length=400)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    fallback_model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=400)
    timeout_seconds: float | None = Field(default=None, ge=5.0, le=900.0)
    max_tokens: int | None = Field(default=None, ge=128, le=8192)
    cache_ttl_seconds: int | None = Field(default=None, ge=1, le=3600)
    cache_max_entries: int | None = Field(default=None, ge=16, le=4096)


class RuntimeChatConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_limit: int | None = Field(default=None, ge=1, le=200)
    rate_limit_per_minute: int | None = Field(default=None, ge=5, le=600)
    context_max_chars: int | None = Field(default=None, ge=2000, le=200000)
    docs_top_k: int | None = Field(default=None, ge=1, le=20)
    docs_search_cache_ttl_seconds: int | None = Field(default=None, ge=5, le=3600)
    docs_answer_cache_ttl_seconds: int | None = Field(default=None, ge=5, le=3600)


class RuntimeDocsConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_outside_project: bool | None = None
    source_scan_cache_ttl_seconds: int | None = Field(default=None, ge=3, le=3600)
    health_cache_ttl_seconds: int | None = Field(default=None, ge=3, le=3600)


class RuntimeFilesConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_outside_project: bool | None = None
    search_cache_ttl_seconds: int | None = Field(default=None, ge=5, le=3600)
    read_max_chars: int | None = Field(default=None, ge=400, le=200000)
    search_max_results: int | None = Field(default=None, ge=1, le=100)


class RuntimeNetboxConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = Field(default=None, min_length=1, max_length=400)
    token: str | None = Field(default=None, max_length=400)
    token_env: str | None = Field(default=None, max_length=120)
    cache_ttl_seconds: int | None = Field(default=None, ge=5, le=3600)
    timeout_seconds: float | None = Field(default=None, ge=3.0, le=120.0)


class RuntimeConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: RuntimeAppConfigModel | None = None
    llm: RuntimeLlmConfigModel | None = None
    chat: RuntimeChatConfigModel | None = None
    docs: RuntimeDocsConfigModel | None = None
    files: RuntimeFilesConfigModel | None = None
    netbox: RuntimeNetboxConfigModel | None = None


class DocsSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=400)
    patterns: list[str] = Field(min_length=1, max_length=24)


class FilesRootModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=400)
    patterns: list[str] = Field(min_length=1, max_length=24)


class UsersGroupModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    allowed_mcp_ids: list[str] = Field(default_factory=list, max_length=64)
    persona_id: str = Field(default="default", min_length=1, max_length=64)


class UsersUserModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=16)
    groups: list[str] = Field(default_factory=list, max_length=32)
    allowed_mcp_ids: list[str] = Field(default_factory=list, max_length=64)
    persona_id: str = Field(default="default", min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=12, max_length=256)


class UsersConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[UsersGroupModel] = Field(default_factory=list)
    users: list[UsersUserModel] = Field(default_factory=list)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {_json_dumps(payload)}\n\n"


def _state() -> tuple[Any, Any, Any, Any]:
    with runtime_lock:
        return settings, llm, registry, assistant


def _request_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client is not None else "unknown"


def _request_is_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def _audit(event: str, *, actor: str = "", request: Request | None = None, **data: Any) -> None:
    payload = {
        "event": event,
        "actor": actor or "anonymous",
        "client_ip": _request_client_ip(request) if request is not None else "",
        **data,
    }
    logger.info("audit %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _write_text_file(path: Path, text: str) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    temp_path = path.parent / f".{path.name}.tmp-{int(time.time() * 1000)}"
    if path.exists():
        backup_path = path.parent / f".{path.name}.bak-{int(time.time() * 1000)}"
        shutil.copy2(path, backup_path)
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if backup_path is not None and backup_path.exists() and not path.exists():
            backup_path.replace(path)
        raise
    return backup_path


def _write_json_file(path: Path, payload: dict[str, Any]) -> Path | None:
    return _write_text_file(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _trimmed_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _validate_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    validated = RuntimeConfigModel.model_validate(config)
    return validated.model_dump(exclude_none=True)


def _validate_docs_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in sources:
        source = DocsSourceModel.model_validate(item)
        if source.id in ids:
            raise HTTPException(status_code=400, detail=f"doppelte_docs_id:{source.id}")
        ids.add(source.id)
        normalized.append(
            {
                "id": source.id,
                "name": source.name.strip(),
                "path": source.path.strip(),
                "patterns": _trimmed_list(source.patterns),
            }
        )
    return normalized


def _validate_files_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in sources:
        root = FilesRootModel.model_validate(item)
        if root.id in ids:
            raise HTTPException(status_code=400, detail=f"doppelte_files_root_id:{root.id}")
        ids.add(root.id)
        normalized.append(
            {
                "id": root.id,
                "name": root.name.strip(),
                "path": root.path.strip(),
                "patterns": _trimmed_list(root.patterns),
            }
        )
    return normalized


def _validate_mcps_config(mcps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in mcps:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="ungueltiger_mcp_eintrag")
        mcp_id = str(item.get("id", "")).strip()
        kind = str(item.get("kind", "")).strip().lower()
        if not mcp_id or not kind:
            raise HTTPException(status_code=400, detail="mcp_id_oder_kind_fehlt")
        if mcp_id in ids:
            raise HTTPException(status_code=400, detail=f"doppelte_mcp_id:{mcp_id}")
        ids.add(mcp_id)
        base = {
            "id": mcp_id,
            "name": str(item.get("name", mcp_id)).strip() or mcp_id,
            "description": str(item.get("description", f"MCP {mcp_id}")).strip() or f"MCP {mcp_id}",
            "kind": kind,
            "enabled": bool(item.get("enabled", True)),
        }
        if kind == "remote_http":
            base_url = str(item.get("base_url", "")).strip()
            if not base_url:
                raise HTTPException(status_code=400, detail=f"remote_base_url_fehlt:{mcp_id}")
            protocol = str(item.get("protocol", "standard_v1")).strip().lower() or "standard_v1"
            if protocol not in {"standard_v1", "satellite_execute_v1"}:
                raise HTTPException(status_code=400, detail=f"ungueltiges_remote_protocol:{mcp_id}")
            module = str(item.get("module", "")).strip().lower()
            start_command = _normalize_command_list(item.get("start_command"), field_name=f"start_command:{mcp_id}")
            stop_command = _normalize_command_list(item.get("stop_command"), field_name=f"stop_command:{mcp_id}")
            status_command = _normalize_command_list(item.get("status_command"), field_name=f"status_command:{mcp_id}")
            working_dir = str(item.get("working_dir", "")).strip()
            normalized.append(
                {
                    **base,
                    "base_url": base_url.rstrip("/"),
                    "protocol": protocol,
                    "module": module,
                    "execute_path": str(item.get("execute_path", "/execute")).strip() or "/execute",
                    "health_path": str(item.get("health_path", "/health")).strip() or "/health",
                    "bearer_token": str(item.get("bearer_token", "")).strip(),
                    "bearer_token_env": str(item.get("bearer_token_env", "")).strip(),
                    "timeout_seconds": max(3.0, float(item.get("timeout_seconds", 15) or 15)),
                    "working_dir": working_dir,
                    "start_command": start_command,
                    "stop_command": stop_command,
                    "status_command": status_command,
                }
            )
            continue
        raise HTTPException(status_code=400, detail=f"mcp_typ_nicht_erlaubt:{kind}")
    return normalized


def _validate_users_config(groups: list[dict[str, Any]], users: list[dict[str, Any]], current_settings: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups_model = [UsersGroupModel.model_validate(item) for item in groups]
    users_model = [UsersUserModel.model_validate(item) for item in users]
    group_ids = {group.id for group in groups_model}
    existing_users = {
        str(item.get("username", "")).strip(): str(item.get("password_sha256", "")).strip()
        for item in _users_config_payload(current_settings).get("users", [])
        if isinstance(item, dict)
    }
    normalized_groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    for group in groups_model:
        if group.id in seen_group_ids:
            raise HTTPException(status_code=400, detail=f"doppelte_gruppen_id:{group.id}")
        seen_group_ids.add(group.id)
        normalized_groups.append(
            {
                "id": group.id,
                "name": group.name.strip(),
                "allowed_mcp_ids": _trimmed_list(group.allowed_mcp_ids),
                "persona_id": group.persona_id.strip() or "default",
            }
        )

    normalized_users: list[dict[str, Any]] = []
    seen_usernames: set[str] = set()
    for user in users_model:
        if user.username in seen_usernames:
            raise HTTPException(status_code=400, detail=f"doppelter_username:{user.username}")
        seen_usernames.add(user.username)
        invalid_groups = [group_id for group_id in user.groups if group_id not in group_ids]
        if invalid_groups:
            raise HTTPException(status_code=400, detail=f"unbekannte_gruppe:{','.join(invalid_groups)}")
        password_hash = existing_users.get(user.username, "")
        if user.password:
            password_hash = hash_password(user.password)
        if not password_hash:
            raise HTTPException(status_code=400, detail=f"passwort_fehlt:{user.username}")
        normalized_users.append(
            {
                "username": user.username.strip(),
                "display_name": user.display_name.strip(),
                "role": "admin" if user.role.strip().lower() == "admin" else "user",
                "password_sha256": password_hash,
                "groups": _trimmed_list(user.groups),
                "allowed_mcp_ids": _trimmed_list(user.allowed_mcp_ids),
                "persona_id": user.persona_id.strip() or "default",
            }
        )
    if not any(user["role"] == "admin" for user in normalized_users):
        raise HTTPException(status_code=400, detail="mindestens_ein_admin_erforderlich")
    return normalized_groups, normalized_users


def _mask_runtime_secrets(config: dict[str, Any]) -> dict[str, Any]:
    masked = json.loads(json.dumps(config))
    llm_section = masked.get("llm")
    if isinstance(llm_section, dict) and llm_section.get("api_key"):
        llm_section["api_key"] = ""
        llm_section["api_key_present"] = True
    netbox_section = masked.get("netbox")
    if isinstance(netbox_section, dict) and netbox_section.get("token"):
        netbox_section["token"] = ""
        netbox_section["token_present"] = True
    return masked


def _sanitize_users_config_for_admin(current_settings: Any) -> dict[str, Any]:
    raw = _users_config_payload(current_settings)
    items: list[dict[str, Any]] = []
    for item in raw.get("users", []):
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "username": str(item.get("username", "")).strip(),
                "display_name": str(item.get("display_name", "")).strip(),
                "role": str(item.get("role", "user")).strip() or "user",
                "groups": list(item.get("groups", [])) if isinstance(item.get("groups"), list) else [],
                "allowed_mcp_ids": list(item.get("allowed_mcp_ids", [])) if isinstance(item.get("allowed_mcp_ids"), list) else [],
                "persona_id": str(item.get("persona_id", "default")).strip() or "default",
                "password_set": bool(str(item.get("password_sha256", "")).strip()),
                "password_scheme": password_hash_scheme(str(item.get("password_sha256", "")).strip()),
                "password_modern": password_hash_is_modern(str(item.get("password_sha256", "")).strip()),
            }
        )
    return {
        "groups": raw.get("groups", []),
        "users": items,
        "setup_required": auth_manager.setup_required(),
    }


def _sanitize_mcp_result_for_session(result: dict[str, Any], session: AuthSession) -> dict[str, Any]:
    if session.is_admin:
        return result

    def walk(value: Any) -> Any:
        blocked_keys = {
            "absolute_path",
            "source_path",
            "index_path",
            "index_meta_path",
            "path_on_disk",
            "mcps_config_path",
            "passwd",
            "runtime_config",
            "log_file",
            "service_log_file",
        }
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items() if key not in blocked_keys}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(result)


def _session_from_request(request: Request) -> AuthSession | None:
    return auth_manager.get_session(request.cookies.get(SESSION_COOKIE, ""))


def _require_session(request: Request) -> AuthSession:
    if auth_manager.setup_required():
        raise HTTPException(status_code=503, detail="setup_required")
    session = _session_from_request(request)
    if session is None:
        raise HTTPException(status_code=401, detail="auth_required")
    return session


def _require_admin(request: Request) -> AuthSession:
    session = _require_session(request)
    if not session.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return session


def _verify_csrf(request: Request, session: AuthSession) -> None:
    token = request.headers.get("x-csrf-token", "").strip()
    if not token or token != session.csrf_token:
        raise HTTPException(status_code=403, detail="csrf_invalid")


def _require_admin_with_csrf(request: Request) -> AuthSession:
    session = _require_admin(request)
    _verify_csrf(request, session)
    return session


def _session_can_access_mcp(session: AuthSession, mcp_id: str) -> bool:
    if session.is_admin:
        return True
    return "*" in session.allowed_mcp_ids or mcp_id in session.allowed_mcp_ids


def _session_can_execute_action(session: AuthSession, current_registry: MCPRegistry, mcp_id: str, action: str) -> bool:
    if session.is_admin:
        return True
    mcp = current_registry.get(mcp_id)
    if mcp is None:
        return False
    normalized = action.strip().lower()
    return normalized in {"health", "query", "search"}


def _filter_mcps_for_session(items: list[dict[str, Any]], session: AuthSession) -> list[dict[str, Any]]:
    if session.is_admin:
        return items
    return [item for item in items if _session_can_access_mcp(session, str(item.get("id", "")))]


def _sanitize_mcp_descriptor_for_user(item: dict[str, Any], *, is_admin: bool) -> dict[str, Any]:
    if is_admin:
        return item
    sanitized = {}
    blocked_keys = {"source_path", "index_path", "index_meta_path", "absolute_path", "base_url", "roots_path", "working_dir"}
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


def _platform_summary() -> dict[str, Any]:
    summary = {"pretty_name": "unknown", "family": "other", "package_manager": "", "setup_hint": "", "python": sys.version.split()[0]}
    os_release = Path("/etc/os-release")
    values: dict[str, str] = {}
    if os_release.exists():
        for line in os_release.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip().strip('"').strip("'")
    distro_id = values.get("id", "").strip().lower()
    distro_like = values.get("id_like", "").strip().lower()
    summary["pretty_name"] = values.get("pretty_name", "").strip() or distro_id or "unknown"
    if distro_id == "ubuntu" or "ubuntu" in distro_like:
        summary["family"] = "ubuntu"
        summary["package_manager"] = "apt-get"
        summary["setup_hint"] = "./scripts/ubuntu-first-setup.sh"
    elif distro_id in {"arch", "cachyos", "manjaro"} or "arch" in distro_like:
        summary["family"] = "arch"
        summary["package_manager"] = "pacman"
        summary["setup_hint"] = "./scripts/arch-first-setup.sh"
    elif shutil.which("apt-get"):
        summary["package_manager"] = "apt-get"
    elif shutil.which("pacman"):
        summary["package_manager"] = "pacman"
    summary["has_systemctl"] = shutil.which("systemctl") is not None
    summary["has_git"] = shutil.which("git") is not None
    summary["has_curl"] = shutil.which("curl") is not None
    summary["has_check_script"] = (settings.base_dir / "check").exists()
    return summary


def _normalize_command_list(value: Any, *, field_name: str) -> list[str]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{field_name}_muss_array_sein")
    normalized: list[str] = []
    for part in value:
        candidate = str(part).strip()
        if not candidate:
            raise HTTPException(status_code=400, detail=f"{field_name}_enthaelt_leeren_wert")
        normalized.append(candidate)
    return normalized


def _find_mcp_config_item(current_settings: Any, mcp_id: str) -> dict[str, Any]:
    config = _mcps_config_payload(current_settings)
    for item in config.get("mcps", []):
        if isinstance(item, dict) and str(item.get("id", "")).strip() == mcp_id:
            return item
    raise HTTPException(status_code=404, detail="mcp_not_found")


def _execute_mcp_control_command(
    current_settings: Any,
    item: dict[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    if str(item.get("kind", "")).strip().lower() != "remote_http":
        raise HTTPException(status_code=400, detail="mcp_control_nur_remote_http")

    command = _normalize_command_list(item.get(f"{action}_command"), field_name=f"{action}_command")
    if not command:
        raise HTTPException(status_code=400, detail=f"{action}_command_nicht_konfiguriert")

    working_dir_raw = str(item.get("working_dir", "")).strip()
    working_dir = Path(working_dir_raw).expanduser() if working_dir_raw else current_settings.base_dir
    if not working_dir.is_absolute():
        working_dir = current_settings.base_dir / working_dir
    working_dir = working_dir.resolve()

    started_at = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(working_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "success": completed.returncode == 0,
        "action": action,
        "mcp_id": str(item.get("id", "")).strip(),
        "command": command,
        "working_dir": str(working_dir),
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
        "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
    }


def _resolve_guide_working_dir(current_settings: Any, item: dict[str, Any]) -> Path:
    working_dir_raw = str(item.get("working_dir", "")).strip()
    working_dir = Path(working_dir_raw).expanduser() if working_dir_raw else current_settings.base_dir
    if not working_dir.is_absolute():
        working_dir = current_settings.base_dir / working_dir
    return working_dir.resolve()


def _command_probe_row(command: list[str], *, working_dir: Path, label: str) -> dict[str, Any]:
    if not command:
        return {"id": label, "label": label, "ok": True, "detail": "nicht konfiguriert"}
    executable = command[0]
    resolved = ""
    if "/" in executable:
        candidate = Path(executable).expanduser()
        if not candidate.is_absolute():
            candidate = working_dir / candidate
        candidate = candidate.resolve()
        resolved = str(candidate)
        ok = candidate.exists() and os.access(candidate, os.X_OK)
    else:
        which = shutil.which(executable)
        resolved = which or ""
        ok = bool(which)
    detail = f"{executable} -> {resolved or 'nicht gefunden'}"
    return {"id": label, "label": label, "ok": ok, "detail": detail}


def _guide_probe_payload(current_settings: Any, body: McpGuideProbeRequest) -> dict[str, Any]:
    normalized_action = body.action.strip().lower()
    if normalized_action not in {"validate", "health", "handshake", "start", "stop", "status"}:
        raise HTTPException(status_code=400, detail="ungueltige_guide_action")
    validated = _validate_mcps_config([body.draft])
    item = validated[0]
    working_dir = _resolve_guide_working_dir(current_settings, item)
    hints = [
        "Fuer Ubuntu ist ein lokaler Reverse Proxy oder localhost-Base-URL meist stabiler als ein frei wechselnder Hostname.",
        "Nutze moeglichst kurze Status-Kommandos und halte Start-/Stop-Kommandos idempotent, damit die Web-UI responsiv bleibt.",
        "Pruefe nach erfolgreichem Handshake erst dann die Uebernahme in den Manager und das Speichern der Live-Konfiguration.",
    ]
    checks = [
        {"id": "base_url", "label": "Base URL", "ok": bool(str(item.get("base_url", "")).strip()), "detail": str(item.get("base_url", "")).strip()},
        {"id": "working_dir", "label": "Working Dir", "ok": working_dir.exists(), "detail": str(working_dir)},
        {"id": "execute_path", "label": "Execute Path", "ok": str(item.get("execute_path", "")).startswith("/"), "detail": str(item.get("execute_path", ""))},
        {"id": "health_path", "label": "Health Path", "ok": str(item.get("health_path", "")).startswith("/"), "detail": str(item.get("health_path", ""))},
        _command_probe_row(item.get("start_command", []), working_dir=working_dir, label="Start Command"),
        _command_probe_row(item.get("status_command", []), working_dir=working_dir, label="Status Command"),
        _command_probe_row(item.get("stop_command", []), working_dir=working_dir, label="Stop Command"),
    ]
    payload: dict[str, Any] = {
        "success": True,
        "action": normalized_action,
        "draft": item,
        "checks": checks,
        "hints": hints,
    }
    if normalized_action == "validate":
        return payload

    if normalized_action in {"start", "stop", "status"}:
        command_result = _execute_mcp_control_command(current_settings, item, action=normalized_action)
        payload["success"] = bool(command_result.get("success"))
        payload["command_result"] = command_result
        return payload

    probe = RemoteHttpMCP(
        mcp_id=str(item.get("id", "")).strip(),
        label=str(item.get("name", "")).strip() or str(item.get("id", "")).strip(),
        description=str(item.get("description", "")).strip(),
        base_url=str(item.get("base_url", "")).strip(),
        execute_path=str(item.get("execute_path", "/execute")).strip() or "/execute",
        health_path=str(item.get("health_path", "/health")).strip() or "/health",
        bearer_token=str(item.get("bearer_token", "")).strip(),
        bearer_token_env=str(item.get("bearer_token_env", "")).strip(),
        timeout_seconds=float(item.get("timeout_seconds", 15) or 15),
    )
    try:
        result = probe.health() if normalized_action == "health" else probe.handshake()
    finally:
        probe.close()
    payload["success"] = result.success
    payload["probe_result"] = result.as_dict()
    return payload


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
    payload = {"mcps": mcps}
    _write_json_file(current_settings.mcps_config_path, payload)


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
    payload = {"groups": groups, "users": users}
    _write_json_file(current_settings.users_config_path, payload)


def _set_user_password(current_settings: Any, username: str, new_password: str) -> None:
    raw = _users_config_payload(current_settings)
    users = raw.get("users", []) if isinstance(raw.get("users"), list) else []
    updated = False
    for item in users:
        if not isinstance(item, dict):
            continue
        if str(item.get("username", "")).strip() != username:
            continue
        item["password_sha256"] = hash_password(new_password)
        updated = True
        break
    if not updated:
        raise HTTPException(status_code=404, detail="user_not_found")
    groups = raw.get("groups", []) if isinstance(raw.get("groups"), list) else []
    _write_users_config(current_settings, groups, users)


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


def _llm_probe_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Antworte nur mit pong."},
        {"role": "user", "content": "ping"},
    ]


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
        mcp_health.append({**item, **_sanitize_mcp_result_for_session(result.as_dict(), session)})
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
    visible_mcps = [_sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in _filter_mcps_for_session(current_registry.list(), session)]
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
        payload["platform"] = _platform_summary()
        payload["paths"] = {
            "runtime_config": str(current_settings.runtime_config_path),
            "mcps_config": str(current_settings.mcps_config_path),
            "passwd": str(current_settings.users_config_path),
            "personas_dir": str(current_settings.personas_dir),
            "system_prompt": str(current_settings.system_prompt_path),
            "log_file": str(current_settings.log_file),
            "service_log_file": str(_service_log_path(current_settings)),
        }
    _record_metric("endpoint", "/api/config", started_at, data={"mcp_count": len(payload["mcps"])})
    return payload


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    if auth_manager.setup_required():
        return {"authenticated": False, "setup_required": True}
    session = _session_from_request(request)
    if session is None:
        raise HTTPException(status_code=401, detail="auth_required")
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
        "csrf_token": session.csrf_token,
        "mcps": [_sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in _filter_mcps_for_session(current_registry.list(), session)],
        "personas": _persona_index(current_settings),
        "app_name": current_settings.app_name,
    }


@app.post("/api/setup/bootstrap")
def setup_bootstrap(body: SetupBootstrapRequest, request: Request, response: Response) -> dict[str, Any]:
    if not auth_manager.setup_required():
        raise HTTPException(status_code=409, detail="setup_already_completed")
    if body.password != body.password_confirm:
        raise HTTPException(status_code=400, detail="password_mismatch")
    groups = _users_config_payload(settings).get("groups", [])
    users = [
        {
            "username": body.username.strip(),
            "display_name": body.display_name.strip(),
            "role": "admin",
            "password_sha256": hash_password(body.password),
            "allowed_mcp_ids": ["*"],
            "groups": [],
            "persona_id": "default",
        }
    ]
    _write_users_config(settings, groups if isinstance(groups, list) else [], users)
    reload_runtime()
    user = auth_manager.verify_credentials(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=500, detail="bootstrap_login_failed")
    session = auth_manager.create_session(user)
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        httponly=True,
        samesite="strict",
        secure=_request_is_secure(request),
        max_age=auth_manager.session_ttl_seconds,
        path="/",
    )
    _audit("setup_bootstrap", actor=user.username, request=request)
    return {
        "success": True,
        "username": user.username,
        "role": user.role,
        "is_admin": user.role == "admin",
        "csrf_token": session.csrf_token,
    }


@app.post("/api/auth/login")
def auth_login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    if auth_manager.setup_required():
        raise HTTPException(status_code=503, detail="setup_required")
    client_ip = _request_client_ip(request)
    limiter_key = f"{client_ip}:{body.username.strip().lower()}"
    if not auth_manager.login_limiter.allow(limiter_key):
        retry_after = auth_manager.login_limiter.retry_after_seconds(limiter_key)
        raise HTTPException(status_code=429, detail=f"login_rate_limited:{retry_after}")
    user = auth_manager.verify_credentials(body.username, body.password)
    if user is None:
        auth_manager.login_limiter.register_failure(limiter_key)
        _audit("login_failed", actor=body.username.strip(), request=request)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    auth_manager.login_limiter.clear(limiter_key)
    session = auth_manager.create_session(user)
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        httponly=True,
        samesite="strict",
        secure=_request_is_secure(request),
        max_age=auth_manager.session_ttl_seconds,
        path="/",
    )
    _audit("login_success", actor=user.username, request=request)
    return {
        "success": True,
        "username": session.username,
        "role": session.role,
        "is_admin": session.is_admin,
        "csrf_token": session.csrf_token,
    }


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    session = _session_from_request(request)
    auth_manager.clear_session(request.cookies.get(SESSION_COOKIE, ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    _audit("logout", actor=session.username if session is not None else "", request=request)
    return {"success": True}


@app.post("/api/auth/password")
def change_own_password(body: ChangeOwnPasswordRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_session(request)
    _verify_csrf(request, session)
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=400, detail="password_mismatch")
    user = auth_manager.verify_credentials(session.username, body.current_password)
    if user is None:
        raise HTTPException(status_code=400, detail="current_password_invalid")
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _set_user_password(current_settings, session.username, body.new_password)
    reload_runtime()
    _audit("password_changed", actor=session.username, request=request)
    _record_metric("endpoint", "/api/auth/password", started_at)
    return {"success": True}


@app.get("/api/mcps")
def list_mcps(request: Request) -> dict[str, Any]:
    session = _require_session(request)
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    return {"items": [_sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in _filter_mcps_for_session(current_registry.list(), session)]}


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
    if not _session_can_execute_action(session, current_registry, mcp_id, body.action):
        raise HTTPException(status_code=403, detail="mcp_action_not_allowed")
    result = current_registry.execute(mcp_id, body.action, body.payload)
    status = 200 if result.success else 400
    _record_metric(
        "mcp",
        f"{mcp_id}:{body.action}",
        started_at,
        ok=result.success,
        data={"mcp_id": mcp_id, "action": body.action, "http_status": status},
    )
    return JSONResponse(_sanitize_mcp_result_for_session(result.as_dict(), session), status_code=status)


@app.get("/api/admin/runtime")
def get_runtime(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {
        "config": _mask_runtime_secrets(load_runtime_config(current_settings.runtime_config_path)),
        "path": str(current_settings.runtime_config_path),
    }


@app.put("/api/admin/runtime")
def put_runtime(body: RuntimeConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    try:
        normalized_config = _normalized_runtime_payload(_validate_runtime_config(body.config))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    previous_config = load_runtime_config(current_settings.runtime_config_path)
    previous_llm = previous_config.get("llm", {}) if isinstance(previous_config.get("llm"), dict) else {}
    previous_netbox = previous_config.get("netbox", {}) if isinstance(previous_config.get("netbox"), dict) else {}
    if isinstance(normalized_config.get("llm"), dict) and not normalized_config["llm"].get("api_key") and previous_llm.get("api_key"):
        normalized_config["llm"]["api_key"] = previous_llm.get("api_key")
    if isinstance(normalized_config.get("netbox"), dict) and not normalized_config["netbox"].get("token") and previous_netbox.get("token"):
        normalized_config["netbox"]["token"] = previous_netbox.get("token")
    _write_json_file(current_settings.runtime_config_path, normalized_config)
    reload_runtime()
    _audit("runtime_updated", actor=session.username, request=request)
    _record_metric("endpoint", "/api/admin/runtime:put", started_at)
    return {"success": True, "path": str(current_settings.runtime_config_path)}


@app.post("/api/admin/llm-probe")
def probe_llm(body: LlmProbeRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin_with_csrf(request)
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
    model_ids: list[str] = []
    models_probe_ok = False
    models_probe_error = ""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(probe_url)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            items = payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(items, list):
                for item in items[:12]:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        model_ids.append(item["id"])
            models_probe_ok = True
    except Exception as exc:
        models_probe_error = str(exc)

    probe_client = LlmClient(
        base_url=base_url,
        model=current_settings.llm_model,
        fallback_model="",
        api_key=current_settings.llm_api_key,
        timeout_seconds=timeout_seconds,
        max_tokens=min(64, current_settings.llm_max_tokens),
    )
    try:
        reply = probe_client.chat(_llm_probe_messages()).strip()
        result = {
            "success": True,
            "base_url": base_url,
            "probe_url": probe_url,
            "chat_url": probe_client._request_url(probe_client.api_mode),
            "status_code": 200,
            "model": current_settings.llm_model,
            "detected_api_mode": probe_client.api_mode,
            "reply_preview": reply[:120],
            "models": model_ids,
            "models_count": len(model_ids),
            "models_probe_ok": models_probe_ok,
            "models_probe_error": models_probe_error,
            "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
        }
        _record_metric(
            "endpoint",
            "/api/admin/llm-probe",
            started_at,
            data={"status_code": 200, "base_url": base_url, "api_mode": probe_client.api_mode},
        )
        return result
    except Exception as exc:
        _record_metric("endpoint", "/api/admin/llm-probe", started_at, ok=False, data={"base_url": base_url, "reason": str(exc)})
        raise HTTPException(status_code=400, detail=f"LLM Probe fehlgeschlagen: {exc}") from exc
    finally:
        probe_client.close()


@app.get("/api/admin/mcps")
def get_mcps_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    config = _mcps_config_payload(current_settings)
    for item in config.get("mcps", []):
        if not isinstance(item, dict):
            continue
        if "token" in item:
            item["token_present"] = bool(str(item.get("token", "")).strip())
            item["token"] = ""
        if "bearer_token" in item:
            item["bearer_token_present"] = bool(str(item.get("bearer_token", "")).strip())
            item["bearer_token"] = ""
    return {"config": config, "path": str(current_settings.mcps_config_path)}


@app.post("/api/admin/mcp-guide/probe")
def probe_mcp_guide(body: McpGuideProbeRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    payload = _guide_probe_payload(current_settings, body)
    _audit("mcp_guide_probe", actor=session.username, request=request, action=body.action.strip().lower(), mcp_id=str(body.draft.get("id", "")).strip())
    _record_metric(
        "endpoint",
        "/api/admin/mcp-guide/probe",
        started_at,
        ok=bool(payload.get("success")),
        data={"action": body.action.strip().lower(), "mcp_id": str(body.draft.get("id", "")).strip()},
    )
    return payload


@app.put("/api/admin/mcps")
def put_mcps_config(body: McpsConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    try:
        mcps = _validate_mcps_config(body.mcps)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    existing = _mcps_config_payload(current_settings)
    existing_index = {
        str(item.get("id", "")).strip(): item
        for item in existing.get("mcps", [])
        if isinstance(item, dict)
    }
    for item in mcps:
        previous = existing_index.get(str(item.get("id", "")).strip(), {})
        if item.get("kind") == "remote_http" and not item.get("bearer_token") and previous.get("bearer_token"):
            item["bearer_token"] = str(previous.get("bearer_token", "")).strip()
    _write_mcps_config(current_settings, mcps)
    reload_runtime()
    _audit("mcps_updated", actor=session.username, request=request, mcps=len(mcps))
    _record_metric("endpoint", "/api/admin/mcps:put", started_at, data={"mcps": len(mcps)})
    return {"success": True, "path": str(current_settings.mcps_config_path)}


@app.post("/api/admin/mcps/{mcp_id}/handshake")
def handshake_mcp(mcp_id: str, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_admin_with_csrf(request)
    _current_settings, _current_llm, current_registry, _current_assistant = _state()
    assert current_registry is not None
    result = current_registry.execute(mcp_id, "handshake", {})
    _record_metric("endpoint", "/api/admin/mcps/handshake", started_at, ok=result.success, data={"mcp_id": mcp_id})
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result.as_dict()


@app.post("/api/admin/mcps/{mcp_id}/control/{action}")
def control_mcp(mcp_id: str, action: str, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    normalized_action = action.strip().lower()
    if normalized_action not in {"start", "stop", "status"}:
        raise HTTPException(status_code=400, detail="ungueltige_mcp_control_action")
    item = _find_mcp_config_item(current_settings, mcp_id)
    result = _execute_mcp_control_command(current_settings, item, action=normalized_action)
    _audit(f"mcp_control_{normalized_action}", actor=session.username, request=request, mcp_id=mcp_id, exit_code=result["exit_code"])
    _record_metric(
        "endpoint",
        "/api/admin/mcps/control",
        started_at,
        ok=result["success"],
        data={"mcp_id": mcp_id, "action": normalized_action, "exit_code": result["exit_code"]},
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/admin/users")
def get_users_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    return {"config": _sanitize_users_config_for_admin(current_settings), "path": str(current_settings.users_config_path)}


@app.put("/api/admin/users")
def put_users_config(body: UsersConfigRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    try:
        groups, users = _validate_users_config(body.groups, body.users, current_settings)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    _write_users_config(current_settings, groups, users)
    reload_runtime()
    _audit("users_updated", actor=session.username, request=request, users=len(users))
    _record_metric("endpoint", "/api/admin/users:put", started_at, data={"users": len(users)})
    return {"success": True, "path": str(current_settings.users_config_path)}


@app.post("/api/admin/users/{username}/password")
def admin_reset_user_password(username: str, body: AdminPasswordResetRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=400, detail="password_mismatch")
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    target_username = username.strip()
    if not target_username:
        raise HTTPException(status_code=400, detail="username_missing")
    _set_user_password(current_settings, target_username, body.new_password)
    reload_runtime()
    _audit("password_reset", actor=session.username, request=request, target_username=target_username)
    _record_metric("endpoint", "/api/admin/users/password", started_at, data={"target_username": target_username})
    return {"success": True, "username": target_username}


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
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    path = _persona_path(current_settings, persona_id)
    _write_text_file(path, body.content.rstrip() + "\n")
    if path == current_settings.system_prompt_path:
        reload_runtime()
    _audit("persona_updated", actor=session.username, request=request, persona_id=persona_id)
    _record_metric("endpoint", "/api/admin/personas:put", started_at, data={"persona_id": persona_id})
    return {"success": True, "id": persona_id, "path": str(path)}


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
    session = _require_admin_with_csrf(request)
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _write_text_file(current_settings.system_prompt_path, body.prompt.rstrip() + "\n")
    reload_runtime()
    _audit("system_prompt_updated", actor=session.username, request=request)
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
    session = _require_admin_with_csrf(request)
    reload_runtime()
    current_settings, _current_llm, _current_registry, _current_assistant = _state()
    _audit("runtime_reloaded", actor=session.username, request=request)
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
    session = _require_admin_with_csrf(request)
    _schedule_execv(body.delay_seconds)
    _audit("process_restart_scheduled", actor=session.username, request=request, delay_seconds=body.delay_seconds)
    _record_metric("endpoint", "/api/admin/control/restart", started_at, data={"delay_seconds": body.delay_seconds})
    return {"success": True, "action": "restart", "delay_seconds": body.delay_seconds}


@app.post("/api/admin/control/shutdown")
def control_shutdown(body: ControlRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_admin_with_csrf(request)
    _schedule_exit(body.delay_seconds)
    _audit("process_shutdown_scheduled", actor=session.username, request=request, delay_seconds=body.delay_seconds)
    _record_metric("endpoint", "/api/admin/control/shutdown", started_at, data={"delay_seconds": body.delay_seconds})
    return {"success": True, "action": "shutdown", "delay_seconds": body.delay_seconds}


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    session = _require_session(request)
    current_settings, _current_llm, _current_registry, current_assistant = _state()
    assert current_assistant is not None
    assert _current_registry is not None
    metadata = dict(body.metadata or {})
    raw_selected = metadata.get("selected_mcp_ids", [])
    if not isinstance(raw_selected, list):
        raw_selected = []
    metadata["selected_mcp_ids"] = [str(mcp_id).strip() for mcp_id in raw_selected if _session_can_access_mcp(session, str(mcp_id).strip())]
    metadata["system_prompt"] = _session_system_prompt(current_settings, session)
    metadata["allow_direct_mcp"] = session.is_admin
    metadata["tool_descriptions"] = [_sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in _filter_mcps_for_session(_current_registry.list(), session)]
    try:
        result = current_assistant.chat(message=body.message, session_id=body.session_id, metadata=metadata)
    except RuntimeError as exc:
        _record_metric("chat", "sync_error", started_at, ok=False, data={"reason": str(exc), "input_chars": len(body.message)})
        if str(exc) == "rate_limited":
            raise HTTPException(status_code=429, detail="rate_limited") from exc
        if str(exc) == "direct_mcp_disabled":
            raise HTTPException(status_code=403, detail="direct_mcp_disabled") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    perf_payload = dict(result.get("perf", {}))
    perf_payload["request_total_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
    perf_payload["transport"] = "sync"
    _record_metric("chat", str(result.get("route", "sync")), started_at, data=perf_payload)
    return {
        **_sanitize_mcp_result_for_session(result, session),
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
                assert _inner_registry is not None
                raw_selected = metadata.get("selected_mcp_ids", [])
                if not isinstance(raw_selected, list):
                    raw_selected = []
                metadata["selected_mcp_ids"] = [str(mcp_id).strip() for mcp_id in raw_selected if _session_can_access_mcp(session, str(mcp_id).strip())]
                metadata["system_prompt"] = _session_system_prompt(current_settings, session)
                metadata["allow_direct_mcp"] = session.is_admin
                metadata["tool_descriptions"] = [_sanitize_mcp_descriptor_for_user(item, is_admin=session.is_admin) for item in _filter_mcps_for_session(_inner_registry.list(), session)]
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
                sanitized_result = _sanitize_mcp_result_for_session(result, session)
                q.put(("meta", {"session_id": sanitized_result["session_id"], "route": sanitized_result["route"], "citations": sanitized_result["citations"]}))
                q.put(("done", sanitized_result))
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
                elif str(exc) == "direct_mcp_disabled":
                    q.put(("error", {"message": "Direkte /mcp Kommandos sind fuer diesen Account deaktiviert."}))
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
