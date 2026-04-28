from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    app_name: str
    host: str
    port: int
    log_level: str
    log_file: Path
    runtime_config_path: Path
    system_prompt_path: Path
    personas_dir: Path
    llm_base_url: str
    llm_model: str
    llm_fallback_model: str
    llm_api_key: str
    llm_timeout_seconds: float
    llm_max_tokens: int
    llm_cache_ttl_seconds: int
    llm_cache_max_entries: int
    chat_history_limit: int
    chat_rate_limit_per_minute: int
    context_max_chars: int
    docs_sources_path: Path
    docs_cache_dir: Path
    docs_top_k: int
    mcps_config_path: Path
    users_config_path: Path
    docs_allow_outside_project: bool
    docs_source_scan_cache_ttl_seconds: int
    docs_health_cache_ttl_seconds: int
    docs_search_cache_ttl_seconds: int
    docs_answer_cache_ttl_seconds: int
    files_sources_path: Path
    files_allow_outside_project: bool
    files_search_cache_ttl_seconds: int
    files_read_max_chars: int
    files_search_max_results: int
    netbox_base_url: str
    netbox_token: str
    netbox_token_env: str
    netbox_cache_ttl_seconds: int
    netbox_timeout_seconds: float


def _seed_file_if_missing(target_path: Path, template_path: Path) -> None:
    if target_path.exists() or not template_path.exists():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(template_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def _ensure_live_state_files(
    *,
    system_prompt_path: Path,
    personas_dir: Path,
    mcps_config_path: Path,
    users_config_path: Path,
) -> None:
    config_dir = BASE_DIR / "config"
    _seed_file_if_missing(mcps_config_path, config_dir / "mcps.json")
    _seed_file_if_missing(users_config_path, config_dir / "users.json")

    personas_dir.mkdir(parents=True, exist_ok=True)
    persona_templates_dir = config_dir / "personas"
    if persona_templates_dir.exists():
        for template in sorted(persona_templates_dir.glob("*.md")):
            _seed_file_if_missing(personas_dir / template.name, template)

    if not system_prompt_path.exists():
        default_persona = personas_dir / "default.md"
        if default_persona.exists():
            _seed_file_if_missing(system_prompt_path, default_persona)


def load_runtime_config(path: Path | None = None) -> dict[str, object]:
    runtime_path = path or (BASE_DIR / "config/runtime.json")
    if not runtime_path.exists():
        return {}
    try:
        data = json.loads(runtime_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_runtime_config(payload: dict[str, object], path: Path | None = None) -> Path:
    runtime_path = path or (BASE_DIR / "config/runtime.json")
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return runtime_path


def _runtime_get(runtime: dict[str, object], *keys: str) -> object | None:
    current: object = runtime
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_setting(runtime: dict[str, object], section: str, key: str, env_name: str, default: str) -> str:
    value = _runtime_get(runtime, section, key)
    if isinstance(value, str):
        return value.strip()
    return _env(env_name, default)


def _int_setting(runtime: dict[str, object], section: str, key: str, env_name: str, default: int) -> int:
    value = _runtime_get(runtime, section, key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return _env_int(env_name, default)


def _float_setting(runtime: dict[str, object], section: str, key: str, env_name: str, default: float) -> float:
    value = _runtime_get(runtime, section, key)
    if isinstance(value, (int, float)):
        return float(value)
    return _env_float(env_name, default)


def _bool_setting(runtime: dict[str, object], section: str, key: str, env_name: str, default: bool) -> bool:
    value = _runtime_get(runtime, section, key)
    if isinstance(value, bool):
        return value
    return _env_bool(env_name, default)


def load_settings() -> Settings:
    _load_dotenv()
    runtime_config_path = _resolve_path(_env("MONO_RUNTIME_CONFIG_PATH", "config/runtime.json"))
    runtime = load_runtime_config(runtime_config_path)
    personas_dir = _resolve_path(_env("WODDI_AI_CONTROL_PERSONAS_DIR", "personas"))
    system_prompt_path = _resolve_path(_env("MONO_SYSTEM_PROMPT_PATH", "personas/default.md"))
    mcps_config_path = _resolve_path(_env("WODDI_AI_CONTROL_MCPS_CONFIG_PATH", "mcps.local.json"))
    users_config_path = _resolve_path(_env("WODDI_AI_CONTROL_USERS_CONFIG_PATH", "passwd.json"))
    _ensure_live_state_files(
        system_prompt_path=system_prompt_path,
        personas_dir=personas_dir,
        mcps_config_path=mcps_config_path,
        users_config_path=users_config_path,
    )
    return Settings(
        base_dir=BASE_DIR,
        app_name=_string_setting(runtime, "app", "name", "WODDI_AI_CONTROL_APP_NAME", "woddi-ai-control"),
        host=_string_setting(runtime, "app", "host", "MONO_HOST", "0.0.0.0"),
        port=_int_setting(runtime, "app", "port", "MONO_PORT", 8095),
        log_level=_string_setting(runtime, "app", "log_level", "MONO_LOG_LEVEL", "INFO"),
        log_file=_resolve_path(_string_setting(runtime, "app", "log_file", "WODDI_AI_CONTROL_LOG_FILE", "logs/woddi-ai-control.log")),
        runtime_config_path=runtime_config_path,
        system_prompt_path=system_prompt_path,
        personas_dir=personas_dir,
        llm_base_url=_string_setting(runtime, "llm", "base_url", "MONO_LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        llm_model=_string_setting(runtime, "llm", "model", "MONO_LLM_MODEL", "llama3.2:latest"),
        llm_fallback_model=_string_setting(runtime, "llm", "fallback_model", "MONO_LLM_FALLBACK_MODEL", ""),
        llm_api_key=_string_setting(runtime, "llm", "api_key", "MONO_LLM_API_KEY", ""),
        llm_timeout_seconds=max(5.0, _float_setting(runtime, "llm", "timeout_seconds", "MONO_LLM_TIMEOUT_SECONDS", 60.0)),
        llm_max_tokens=max(128, _int_setting(runtime, "llm", "max_tokens", "MONO_LLM_MAX_TOKENS", 1400)),
        llm_cache_ttl_seconds=max(1, _int_setting(runtime, "llm", "cache_ttl_seconds", "MONO_LLM_CACHE_TTL_SECONDS", 45)),
        llm_cache_max_entries=max(16, _int_setting(runtime, "llm", "cache_max_entries", "MONO_LLM_CACHE_MAX_ENTRIES", 512)),
        chat_history_limit=max(1, _int_setting(runtime, "chat", "history_limit", "MONO_CHAT_HISTORY_LIMIT", 12)),
        chat_rate_limit_per_minute=max(5, _int_setting(runtime, "chat", "rate_limit_per_minute", "MONO_CHAT_RATE_LIMIT_PER_MINUTE", 90)),
        context_max_chars=max(2000, _int_setting(runtime, "chat", "context_max_chars", "MONO_CONTEXT_MAX_CHARS", 18000)),
        docs_sources_path=_resolve_path(_env("MONO_DOCS_SOURCES_PATH", "config/docs_sources.json")),
        docs_cache_dir=_resolve_path(_env("MONO_DOCS_CACHE_DIR", "data/cache")),
        docs_top_k=max(1, _int_setting(runtime, "chat", "docs_top_k", "MONO_DOCS_TOP_K", 4)),
        mcps_config_path=mcps_config_path,
        users_config_path=users_config_path,
        docs_allow_outside_project=_bool_setting(runtime, "docs", "allow_outside_project", "MONO_DOCS_ALLOW_OUTSIDE_PROJECT", False),
        docs_source_scan_cache_ttl_seconds=max(
            3,
            _int_setting(runtime, "docs", "source_scan_cache_ttl_seconds", "MONO_DOCS_SOURCE_SCAN_CACHE_TTL_SECONDS", 20),
        ),
        docs_health_cache_ttl_seconds=max(
            3,
            _int_setting(runtime, "docs", "health_cache_ttl_seconds", "MONO_DOCS_HEALTH_CACHE_TTL_SECONDS", 15),
        ),
        docs_search_cache_ttl_seconds=max(5, _int_setting(runtime, "chat", "docs_search_cache_ttl_seconds", "MONO_DOCS_SEARCH_CACHE_TTL_SECONDS", 120)),
        docs_answer_cache_ttl_seconds=max(5, _int_setting(runtime, "chat", "docs_answer_cache_ttl_seconds", "MONO_DOCS_ANSWER_CACHE_TTL_SECONDS", 120)),
        files_sources_path=_resolve_path(_env("WODDI_AI_CONTROL_FILES_SOURCES_PATH", "config/files_sources.json")),
        files_allow_outside_project=_bool_setting(runtime, "files", "allow_outside_project", "WODDI_AI_CONTROL_FILES_ALLOW_OUTSIDE_PROJECT", False),
        files_search_cache_ttl_seconds=max(
            5,
            _int_setting(runtime, "files", "search_cache_ttl_seconds", "WODDI_AI_CONTROL_FILES_SEARCH_CACHE_TTL_SECONDS", 45),
        ),
        files_read_max_chars=max(400, _int_setting(runtime, "files", "read_max_chars", "WODDI_AI_CONTROL_FILES_READ_MAX_CHARS", 12000)),
        files_search_max_results=max(1, _int_setting(runtime, "files", "search_max_results", "WODDI_AI_CONTROL_FILES_SEARCH_MAX_RESULTS", 8)),
        netbox_base_url=_string_setting(runtime, "netbox", "base_url", "MONO_NETBOX_BASE_URL", "").rstrip("/"),
        netbox_token=_string_setting(runtime, "netbox", "token", "MONO_NETBOX_TOKEN", ""),
        netbox_token_env=_string_setting(runtime, "netbox", "token_env", "MONO_NETBOX_TOKEN_ENV", ""),
        netbox_cache_ttl_seconds=max(5, _int_setting(runtime, "netbox", "cache_ttl_seconds", "MONO_NETBOX_CACHE_TTL_SECONDS", 45)),
        netbox_timeout_seconds=max(3.0, _float_setting(runtime, "netbox", "timeout_seconds", "MONO_NETBOX_TIMEOUT_SECONDS", 12.0)),
    )


def configure_logging(settings: Settings) -> None:
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    if not root.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(stream_handler)

    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=1_500_000,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
