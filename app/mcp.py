from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .llm import LlmClient


logger = logging.getLogger(__name__)


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
        timeout = httpx.Timeout(
            connect=max(3.0, self.timeout_seconds),
            read=max(3.0, self.timeout_seconds),
            write=max(3.0, self.timeout_seconds),
            pool=10.0,
        )
        self._client = httpx.Client(timeout=timeout)

    def descriptor(self) -> dict[str, Any]:
        base = super().descriptor()
        base.update(
            {
                "kind": "remote_http",
                "base_url": self.base_url,
                "execute_path": self.execute_path,
                "health_path": self.health_path,
            }
        )
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
            response = self._client.post(f"{self.base_url}{self.execute_path}", headers=self._headers(), json=probe_payload)
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
            return MCPResult(
                True,
                self.mcp_id,
                normalized,
                "Remote MCP Antwort erfolgreich.",
                {"response": raw if isinstance(raw, dict) else {"raw": raw}},
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return MCPResult(False, self.mcp_id, normalized, f"Remote MCP HTTP Fehler {status}.", {}, f"http_status_{status}")
        except Exception as exc:
            return MCPResult(False, self.mcp_id, normalized, f"Remote MCP Fehler: {exc}", {}, "request_error")

    def close(self) -> None:
        self._client.close()


class MCPRegistry:
    def __init__(self, *, settings: Settings, llm: LlmClient) -> None:
        del llm
        self.settings = settings
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
            if kind != "remote_http":
                logger.info("ignoring unsupported built-in MCP kind: %s (%s)", kind, mcp_id)
                continue
            label = str(item.get("name", mcp_id)).strip() or mcp_id
            description = str(item.get("description", f"MCP {label}")).strip() or f"MCP {label}"
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

    def list(self) -> list[dict[str, Any]]:
        return [mcp.descriptor() for mcp in self._mcps.values()]

    def ids(self) -> list[str]:
        return list(self._mcps.keys())

    def get(self, mcp_id: str) -> BaseMCP | None:
        return self._mcps.get(mcp_id)

    def execute(self, mcp_id: str, action: str, payload: dict[str, Any]) -> MCPResult:
        mcp = self._mcps.get(mcp_id)
        if mcp is None:
            return MCPResult(False, mcp_id, action, "MCP nicht gefunden.", {}, "mcp_not_found")
        return mcp.execute(action, payload)

    def close(self) -> None:
        for mcp in self._mcps.values():
            close_fn = getattr(mcp, "close", None)
            if callable(close_fn):
                close_fn()
