from __future__ import annotations

import json
import unittest

import httpx

from app.mcp import RemoteHttpMCP


class McpHttpTests(unittest.TestCase):
    def _build_mcp(self, handler: httpx.MockTransport) -> RemoteHttpMCP:
        mcp = RemoteHttpMCP(
            mcp_id="netbox",
            label="NetBox Labs MCP",
            description="Test MCP",
            base_url="http://mcp.local",
            protocol="mcp_http_v1",
            execute_path="/mcp",
            health_path="/health",
            timeout_seconds=10,
        )
        mcp._client.close()  # noqa: SLF001 - deterministic transport for tests
        mcp._client = httpx.Client(transport=handler, timeout=10.0)
        return mcp

    def test_mcp_http_handshake_lists_tools_without_auth_header(self) -> None:
        calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            calls.append((request.url.path, payload, dict(request.headers)))
            if payload["method"] == "initialize":
                return httpx.Response(
                    200,
                    request=request,
                    headers={"Mcp-Session-Id": "session-123"},
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "serverInfo": {"name": "netbox-mcp-server", "version": "1.0.0"},
                            "capabilities": {"tools": {}},
                        },
                    },
                )
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202, request=request, json={})
            if payload["method"] == "tools/list":
                self.assertEqual(request.headers.get("Mcp-Session-Id"), "session-123")
                self.assertIsNone(request.headers.get("Authorization"))
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "tools": [
                                {"name": "get_objects", "description": "Get NetBox objects"},
                                {"name": "get_changelogs", "description": "Get changelogs"},
                            ]
                        },
                    },
                )
            self.fail(f"Unexpected method: {payload['method']}")

        mcp = self._build_mcp(httpx.MockTransport(handler))
        try:
            result = mcp.handshake()
        finally:
            mcp.close()
        self.assertTrue(result.success)
        self.assertEqual(result.data["session_id"], "session-123")
        self.assertEqual(len(result.data["tools"]), 2)
        methods = [payload["method"] for _path, payload, _headers in calls]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list"])

    def test_mcp_http_call_tool(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            if payload["method"] == "tools/call":
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"content": [{"type": "text", "text": "router-a"}]},
                    },
                )
            self.fail(f"Unexpected method: {payload['method']}")

        mcp = self._build_mcp(httpx.MockTransport(handler))
        try:
            result = mcp.execute("call", {"tool_name": "get_objects", "arguments": {"object_type": "devices"}})
        finally:
            mcp.close()
        self.assertTrue(result.success)
        self.assertEqual(result.data["tool_name"], "get_objects")
        self.assertEqual(result.data["arguments"]["object_type"], "devices")


if __name__ == "__main__":
    unittest.main()
