from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
        protocol: str = "standard_v1",
        module: str = "",
        execute_path: str = "/execute",
        health_path: str = "/health",
        bearer_token: str = "",
        bearer_token_env: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(mcp_id, label, description)
        self.base_url = str(base_url).strip().rstrip("/")
        self.protocol = (str(protocol or "standard_v1").strip().lower() or "standard_v1")
        self.module = str(module or "").strip().lower()
        self.execute_path = str(execute_path or "/execute").strip() or "/execute"
        self.health_path = str(health_path or "/health").strip() or "/health"
        self.bearer_token = bearer_token.strip()
        self.bearer_token_env = bearer_token_env.strip()
        self.timeout_seconds = max(3.0, float(timeout_seconds))
        self._rpc_counter = 0
        self._mcp_session_id = ""
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
                "protocol": self.protocol,
                "module": self.module,
                "base_url": self.base_url,
                "execute_path": self.execute_path,
                "health_path": self.health_path,
            }
        )
        return base

    def _is_mcp_http(self) -> bool:
        return self.protocol == "mcp_http_v1"

    def _execute_request_body(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = action.strip().lower() or "health"
        if self.protocol == "satellite_execute_v1":
            module = self.module or self.mcp_id
            inner_payload = {"action": normalized, **payload}
            return {"module": module, "payload": inner_payload}
        return {"action": normalized, "payload": payload}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = self.bearer_token or (os.getenv(self.bearer_token_env, "").strip() if self.bearer_token_env else "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        if self._is_mcp_http():
            headers["MCP-Protocol-Version"] = "2025-03-26"
        return headers

    def _next_rpc_id(self) -> str:
        self._rpc_counter += 1
        return f"{self.mcp_id}-{self._rpc_counter}-{uuid4().hex[:6]}"

    def _mcp_endpoint_url(self) -> str:
        return f"{self.base_url}{self.execute_path}"

    def _remember_mcp_session(self, response: httpx.Response) -> None:
        session_id = response.headers.get("Mcp-Session-Id", "").strip()
        if session_id:
            self._mcp_session_id = session_id

    def _mcp_http_request(
        self,
        *,
        method: str,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        expect_result: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if request_id is not None:
            body["id"] = request_id
        response = self._client.post(self._mcp_endpoint_url(), headers=self._headers(), json=body)
        self._remember_mcp_session(response)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("mcp_http_invalid_response")
        if isinstance(payload.get("error"), dict):
            message = str(payload["error"].get("message", "MCP error")).strip() or "MCP error"
            code = payload["error"].get("code")
            raise RuntimeError(f"{message} ({code})" if code is not None else message)
        if not expect_result:
            return payload
        result = payload.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def _mcp_http_initialize(self) -> dict[str, Any]:
        init_result = self._mcp_http_request(
            method="initialize",
            request_id=self._next_rpc_id(),
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "woddi-ai-control", "version": "0.2.0"},
            },
        )
        try:
            self._mcp_http_request(
                method="notifications/initialized",
                params={},
                expect_result=False,
            )
        except Exception:
            logger.debug("MCP initialized notification failed for %s", self.mcp_id, exc_info=True)
        return init_result

    def _mcp_http_tools(self) -> dict[str, Any]:
        return self._mcp_http_request(
            method="tools/list",
            request_id=self._next_rpc_id(),
            params={},
        )

    def _mcp_http_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_http_request(
            method="tools/call",
            request_id=self._next_rpc_id(),
            params={"name": tool_name, "arguments": arguments},
        )

    def health(self) -> MCPResult:
        if not self.base_url:
            return MCPResult(False, self.mcp_id, "health", "Remote MCP base_url fehlt.", {}, "missing_base_url")
        if self._is_mcp_http():
            try:
                initialize = self._mcp_http_initialize()
                server_info = initialize.get("serverInfo", {}) if isinstance(initialize.get("serverInfo"), dict) else {}
                return MCPResult(
                    True,
                    self.mcp_id,
                    "health",
                    "MCP HTTP Endpoint erreichbar.",
                    {
                        "base_url": self.base_url,
                        "mcp_url": self._mcp_endpoint_url(),
                        "protocol": self.protocol,
                        "session_id": self._mcp_session_id,
                        "server_info": server_info,
                        "initialize": initialize,
                    },
                )
            except Exception as exc:
                return MCPResult(
                    False,
                    self.mcp_id,
                    "health",
                    f"MCP HTTP Endpoint nicht erreichbar: {exc}",
                    {"base_url": self.base_url, "mcp_url": self._mcp_endpoint_url(), "protocol": self.protocol},
                    "request_error",
                )
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
        if self._is_mcp_http():
            try:
                initialize = self._mcp_http_initialize()
                tools_result = self._mcp_http_tools()
                tools = tools_result.get("tools", []) if isinstance(tools_result.get("tools"), list) else []
                return MCPResult(
                    True,
                    self.mcp_id,
                    "handshake",
                    "MCP HTTP Handshake erfolgreich.",
                    {
                        "base_url": self.base_url,
                        "mcp_url": self._mcp_endpoint_url(),
                        "protocol": self.protocol,
                        "session_id": self._mcp_session_id,
                        "server_info": initialize.get("serverInfo", {}),
                        "capabilities": initialize.get("capabilities", {}),
                        "tools": tools,
                        "initialize": initialize,
                    },
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                return MCPResult(
                    False,
                    self.mcp_id,
                    "handshake",
                    f"MCP HTTP Handshake HTTP Fehler {status}.",
                    {"base_url": self.base_url, "mcp_url": self._mcp_endpoint_url(), "protocol": self.protocol},
                    f"http_status_{status}",
                )
            except Exception as exc:
                return MCPResult(
                    False,
                    self.mcp_id,
                    "handshake",
                    f"MCP HTTP Handshake Fehler: {exc}",
                    {"base_url": self.base_url, "mcp_url": self._mcp_endpoint_url(), "protocol": self.protocol},
                    "request_error",
                )
        if self.protocol == "satellite_execute_v1":
            health_result = self.health()
            if not health_result.success:
                return MCPResult(
                    False,
                    self.mcp_id,
                    "handshake",
                    health_result.message,
                    health_result.data,
                    health_result.error,
                )
            capabilities = {
                "protocol": self.protocol,
                "module": self.module or self.mcp_id,
                "actions": [
                    "health",
                    "devices",
                    "ip-addresses",
                    "get_objects",
                    "get_object_by_id",
                    "get_changelogs",
                ],
                "service": self.label,
            }
            return MCPResult(
                True,
                self.mcp_id,
                "handshake",
                "Satellite MCP Health erfolgreich; Capabilities lokal abgeleitet.",
                {
                    "base_url": self.base_url,
                    "execute_url": f"{self.base_url}{self.execute_path}",
                    "health_url": f"{self.base_url}{self.health_path}",
                    "capabilities": capabilities,
                },
            )
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
        if self._is_mcp_http():
            try:
                if normalized in {"probe", "tools"}:
                    initialize = self._mcp_http_initialize()
                    tools_result = self._mcp_http_tools()
                    return MCPResult(
                        True,
                        self.mcp_id,
                        normalized,
                        "MCP HTTP Probe erfolgreich.",
                        {
                            "base_url": self.base_url,
                            "mcp_url": self._mcp_endpoint_url(),
                            "protocol": self.protocol,
                            "session_id": self._mcp_session_id,
                            "server_info": initialize.get("serverInfo", {}),
                            "capabilities": initialize.get("capabilities", {}),
                            "tools": tools_result.get("tools", []),
                        },
                    )
                if normalized == "call":
                    tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
                    if not tool_name:
                        return MCPResult(
                            False,
                            self.mcp_id,
                            normalized,
                            "Fuer MCP HTTP tool call fehlt tool_name.",
                            {"hint": "Nutze action=call und payload.tool_name plus payload.arguments."},
                            "missing_tool_name",
                        )
                    raw_arguments = payload.get("arguments", payload.get("args", {}))
                    arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
                    result = self._mcp_http_call_tool(tool_name, arguments)
                    return MCPResult(
                        True,
                        self.mcp_id,
                        normalized,
                        f"MCP HTTP Tool {tool_name} erfolgreich ausgefuehrt.",
                        {"tool_name": tool_name, "arguments": arguments, "response": result},
                    )
                return MCPResult(
                    False,
                    self.mcp_id,
                    normalized,
                    "Dieses MCP nutzt generisches MCP HTTP. Verwende health, handshake, probe/tools oder call.",
                    {
                        "supported_actions": ["health", "handshake", "probe", "tools", "call"],
                        "hint": "Direkter Aufruf: action=call, payload={\"tool_name\":\"get_objects\",\"arguments\":{...}}",
                    },
                    "unsupported_action",
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                return MCPResult(
                    False,
                    self.mcp_id,
                    normalized,
                    f"MCP HTTP Fehler {status}.",
                    {"base_url": self.base_url, "mcp_url": self._mcp_endpoint_url(), "protocol": self.protocol},
                    f"http_status_{status}",
                )
            except Exception as exc:
                return MCPResult(
                    False,
                    self.mcp_id,
                    normalized,
                    f"MCP HTTP Fehler: {exc}",
                    {"base_url": self.base_url, "mcp_url": self._mcp_endpoint_url(), "protocol": self.protocol},
                    "request_error",
                )
        try:
            response = self._client.post(
                f"{self.base_url}{self.execute_path}",
                headers=self._headers(),
                json=self._execute_request_body(normalized, payload),
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
                protocol=str(item.get("protocol", "standard_v1")).strip() or "standard_v1",
                module=str(item.get("module", "")).strip(),
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
