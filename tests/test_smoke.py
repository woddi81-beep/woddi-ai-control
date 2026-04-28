from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import HTTPException, Response
from starlette.requests import Request

from app.cli import _build_prerequisite_report
from app.main import (
    AdminPasswordResetRequest,
    MCPRequest,
    McpsConfigRequest,
    RuntimeConfigRequest,
    SetupBootstrapRequest,
    UsersConfigRequest,
    admin_reset_user_password,
    auth_manager,
    change_own_password,
    auth_session,
    chat as chat_endpoint,
    execute_mcp,
    get_mcps_config,
    get_runtime,
    get_users_config,
    put_mcps_config,
    put_runtime,
    put_users_config,
    reload_runtime,
    setup_bootstrap,
)
from app.security import password_hash_is_modern


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PASSWD_PATH = PROJECT_ROOT / "passwd.json"
RUNTIME_PATH = PROJECT_ROOT / "config/runtime.json"
MCPS_PATH = PROJECT_ROOT / "mcps.local.json"


def build_request(
    *,
    cookie_token: str = "",
    client_ip: str = "127.0.0.1",
    scheme: str = "http",
    method: str = "GET",
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    request_headers: list[tuple[bytes, bytes]] = list(headers or [])
    if cookie_token:
        request_headers.append((b"cookie", f"woddi_ai_control_session={cookie_token}".encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": request_headers,
        "client": (client_ip, 12345),
        "server": ("testserver", 80),
        "scheme": scheme,
    }
    return Request(scope)


def extract_cookie_token(response: Response) -> str:
    raw_cookie = response.headers.get("set-cookie", "")
    parts = dict(parse_qsl(raw_cookie.replace(";", "&"), keep_blank_values=True))
    return parts.get("woddi_ai_control_session", "")


class WoddiAiControlSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_passwd = PASSWD_PATH.read_text(encoding="utf-8")
        self._original_runtime = RUNTIME_PATH.read_text(encoding="utf-8")
        self._original_mcps = MCPS_PATH.read_text(encoding="utf-8")
        self._cleanup_backup_files()
        auth_manager._sessions.clear()  # noqa: SLF001 - isolate in-memory sessions between tests

    def tearDown(self) -> None:
        PASSWD_PATH.write_text(self._original_passwd, encoding="utf-8")
        RUNTIME_PATH.write_text(self._original_runtime, encoding="utf-8")
        MCPS_PATH.write_text(self._original_mcps, encoding="utf-8")
        auth_manager._sessions.clear()  # noqa: SLF001 - isolate in-memory sessions between tests
        self._cleanup_backup_files()
        reload_runtime()

    def _cleanup_backup_files(self) -> None:
        for path in PROJECT_ROOT.glob(".passwd.json.bak-*"):
            path.unlink(missing_ok=True)
        for path in PROJECT_ROOT.glob(".mcps.local.json.bak-*"):
            path.unlink(missing_ok=True)
        for path in (PROJECT_ROOT / "config").glob(".runtime.json.bak-*"):
            path.unlink(missing_ok=True)

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _empty_users_payload(self) -> dict[str, object]:
        return {
            "groups": [],
            "users": [],
        }

    def _remote_mcp_payload(self) -> dict[str, object]:
        return {
            "mcps": [
                {
                    "id": "remote-main",
                    "name": "Remote Main",
                    "description": "Externer Test-MCP",
                    "kind": "remote_http",
                    "enabled": True,
                    "base_url": "http://127.0.0.1:65534",
                    "execute_path": "/execute",
                    "health_path": "/health",
                    "bearer_token_env": "REMOTE_TEST_TOKEN",
                    "timeout_seconds": 3,
                    "working_dir": "/tmp",
                    "start_command": ["yes"],
                    "stop_command": ["yes"],
                    "status_command": ["yes"],
                }
            ]
        }

    def _bootstrap_admin(self, username: str = "rootadmin", password: str = "VerySecurePass123!") -> str:
        self._write_json(PASSWD_PATH, self._empty_users_payload())
        reload_runtime()
        response = Response()
        result = setup_bootstrap(
            SetupBootstrapRequest(
                username=username,
                display_name="Root Admin",
                password=password,
                password_confirm=password,
            ),
            build_request(),
            response,
        )
        self.assertTrue(result["success"])
        token = extract_cookie_token(response)
        self.assertTrue(token)
        return token

    def _admin_request(self) -> Request:
        token = self._bootstrap_admin()
        return build_request(cookie_token=token)

    def _csrf_request(self, path: str = "/") -> Request:
        user = auth_manager.verify_credentials("rootadmin", "VerySecurePass123!")
        self.assertIsNotNone(user)
        session = auth_manager.create_session(user)
        return build_request(
            cookie_token=session.token,
            method="POST",
            path=path,
            headers=[(b"x-csrf-token", session.csrf_token.encode("utf-8"))],
        )

    def test_bootstrap_flow_requires_initial_setup(self) -> None:
        self._write_json(PASSWD_PATH, self._empty_users_payload())
        reload_runtime()

        session_response = auth_session(build_request())
        self.assertEqual(session_response, {"authenticated": False, "setup_required": True})

        token = self._bootstrap_admin()
        session_after = auth_session(build_request(cookie_token=token))
        self.assertTrue(session_after["authenticated"])
        self.assertTrue(session_after["is_admin"])

        stored = json.loads(PASSWD_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(stored["users"]), 1)
        self.assertTrue(password_hash_is_modern(stored["users"][0]["password_sha256"]))

    def test_admin_users_api_redacts_hashes_and_preserves_passwords(self) -> None:
        self._bootstrap_admin()
        admin_request = self._csrf_request("/api/admin/users")
        users_payload = get_users_config(admin_request)
        admin_user = users_payload["config"]["users"][0]
        self.assertNotIn("password_sha256", admin_user)
        self.assertTrue(admin_user["password_set"])
        self.assertTrue(admin_user["password_modern"])

        put_users_config(
            UsersConfigRequest(
                groups=users_payload["config"]["groups"],
                users=[
                    {
                        "username": "rootadmin",
                        "display_name": "Root Admin Updated",
                        "role": "admin",
                        "groups": [],
                        "allowed_mcp_ids": ["*"],
                        "persona_id": "default",
                    },
                    {
                        "username": "operator",
                        "display_name": "Ops User",
                        "role": "user",
                        "groups": ["ops"],
                        "allowed_mcp_ids": [],
                        "persona_id": "network-ops",
                        "password": "OperatorPass123!",
                    },
                ],
            ),
            admin_request,
        )

        self.assertIsNotNone(auth_manager.verify_credentials("rootadmin", "VerySecurePass123!"))
        self.assertIsNotNone(auth_manager.verify_credentials("operator", "OperatorPass123!"))

    def test_password_change_and_admin_reset_require_csrf(self) -> None:
        token = self._bootstrap_admin()

        with self.assertRaises(HTTPException) as own_without_csrf:
            change_own_password(
                type(
                    "Body",
                    (),
                    {
                        "current_password": "VerySecurePass123!",
                        "new_password": "ChangedSecurePass123!",
                        "new_password_confirm": "ChangedSecurePass123!",
                    },
                )(),
                build_request(cookie_token=token, method="POST", path="/api/auth/password"),
            )
        self.assertEqual(own_without_csrf.exception.status_code, 403)

        own_request = self._csrf_request("/api/auth/password")
        result = change_own_password(
            type(
                "Body",
                (),
                {
                    "current_password": "VerySecurePass123!",
                    "new_password": "ChangedSecurePass123!",
                    "new_password_confirm": "ChangedSecurePass123!",
                },
            )(),
            own_request,
        )
        self.assertTrue(result["success"])
        self.assertIsNotNone(auth_manager.verify_credentials("rootadmin", "ChangedSecurePass123!"))

        with self.assertRaises(HTTPException) as admin_without_csrf:
            admin_reset_user_password(
                "rootadmin",
                AdminPasswordResetRequest(new_password="ResetSecurePass123!", new_password_confirm="ResetSecurePass123!"),
                build_request(cookie_token=token, method="POST", path="/api/admin/users/rootadmin/password"),
            )
        self.assertEqual(admin_without_csrf.exception.status_code, 403)

        reset_request = self._csrf_request("/api/admin/users/rootadmin/password")
        reset_result = admin_reset_user_password(
            "rootadmin",
            AdminPasswordResetRequest(new_password="ResetSecurePass123!", new_password_confirm="ResetSecurePass123!"),
            reset_request,
        )
        self.assertTrue(reset_result["success"])
        self.assertIsNotNone(auth_manager.verify_credentials("rootadmin", "ResetSecurePass123!"))

    def test_non_admin_mcp_actions_are_restricted(self) -> None:
        admin_request = self._admin_request()
        self._write_json(MCPS_PATH, self._remote_mcp_payload())
        reload_runtime()
        put_users_config(
            UsersConfigRequest(
                groups=[
                    {
                        "id": "ops",
                        "name": "Operations",
                        "allowed_mcp_ids": ["remote-main"],
                        "persona_id": "network-ops",
                    }
                ],
                users=[
                    {
                        "username": "rootadmin",
                        "display_name": "Root Admin",
                        "role": "admin",
                        "groups": [],
                        "allowed_mcp_ids": ["*"],
                        "persona_id": "default",
                    },
                    {
                        "username": "operator",
                        "display_name": "Ops User",
                        "role": "user",
                        "groups": ["ops"],
                        "allowed_mcp_ids": [],
                        "persona_id": "network-ops",
                        "password": "OperatorPass123!",
                    },
                ],
            ),
            admin_request,
        )
        operator = auth_manager.verify_credentials("operator", "OperatorPass123!")
        self.assertIsNotNone(operator)
        operator_session = auth_manager.create_session(operator)
        operator_request = build_request(cookie_token=operator_session.token)

        allowed_read = execute_mcp(
            "remote-main",
            MCPRequest(action="health", payload={}),
            operator_request,
        )
        self.assertEqual(allowed_read.status_code, 400)
        self.assertNotIn("absolute_path", allowed_read.body.decode("utf-8"))
        self.assertNotIn("base_url", allowed_read.body.decode("utf-8"))

        with self.assertRaises(HTTPException) as blocked_reindex:
            execute_mcp("remote-main", MCPRequest(action="handshake", payload={}), operator_request)
        self.assertEqual(blocked_reindex.exception.status_code, 403)

        with self.assertRaises(HTTPException) as blocked_direct:
            chat_endpoint(
                type("ChatRequestObj", (), {"message": '/mcp remote-main health {}', "session_id": None, "metadata": None})(),
                operator_request,
            )
        self.assertEqual(blocked_direct.exception.status_code, 403)

    def test_admin_config_endpoints_redact_secrets_and_create_backups(self) -> None:
        admin_request = self._admin_request()

        runtime_payload = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        runtime_payload["llm"]["api_key"] = "llm-secret-key"
        put_runtime(RuntimeConfigRequest(config=runtime_payload), admin_request)

        runtime_response = get_runtime(admin_request)
        runtime_config = runtime_response["config"]
        self.assertEqual(runtime_config["llm"]["api_key"], "")
        self.assertTrue(runtime_config["llm"]["api_key_present"])
        self.assertTrue(any((PROJECT_ROOT / "config").glob(".runtime.json.bak-*")))

        mcps_payload = self._remote_mcp_payload()
        for item in mcps_payload["mcps"]:
            if item.get("kind") == "remote_http":
                item["enabled"] = True
                item["bearer_token"] = "remote-inline-secret"
        put_mcps_config(McpsConfigRequest(mcps=mcps_payload["mcps"]), admin_request)

        mcps_response = get_mcps_config(admin_request)
        remote_item = next(item for item in mcps_response["config"]["mcps"] if item["kind"] == "remote_http")
        self.assertEqual(remote_item["bearer_token"], "")
        self.assertTrue(remote_item["bearer_token_present"])
        self.assertTrue(any(PROJECT_ROOT.glob(".mcps.local.json.bak-*")))

    def test_cli_prerequisites_include_control_configs(self) -> None:
        report = _build_prerequisite_report(argparse.Namespace(systemd="none"))
        names = {item["name"] for item in report.get("checks", [])}
        self.assertIn("file_files_sources.json", names)
        self.assertIn("file_mcps.json", names)
        self.assertIn("file_passwd.json", names)
        self.assertIn("file_default.md", names)


if __name__ == "__main__":
    unittest.main()
