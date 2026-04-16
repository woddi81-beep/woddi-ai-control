from __future__ import annotations

import argparse
import unittest

from app.cli import _build_prerequisite_report
from app.main import _docs_sources_payload, _files_sources_payload, _mcps_config_payload, _state, auth_manager


class WoddiAiControlSmokeTests(unittest.TestCase):
    def test_mcp_config_exposes_files_and_netbox(self) -> None:
        settings, _llm, registry, _assistant = _state()
        payload = _mcps_config_payload(settings)
        kinds = {item.get("kind") for item in payload.get("mcps", [])}
        ids = {item.get("id") for item in registry.list()}
        self.assertIn("files", kinds)
        self.assertIn("netbox", kinds)
        self.assertIn("files-main", ids)
        self.assertIn("netbox-main", ids)

    def test_admin_source_helpers_return_configs(self) -> None:
        settings, _llm, _registry, _assistant = _state()
        docs_payload = _docs_sources_payload(settings)
        files_payload = _files_sources_payload(settings)
        self.assertGreaterEqual(len(docs_payload.get("sources", [])), 1)
        self.assertGreaterEqual(len(files_payload.get("sources", [])), 1)

    def test_files_search_returns_hits(self) -> None:
        _settings, _llm, registry, _assistant = _state()
        result = registry.execute("files-main", "search", {"query": "woddi-ai-control", "limit": 5})
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.data.get("results", [])), 1)

    def test_files_read_reads_project_readme(self) -> None:
        _settings, _llm, registry, _assistant = _state()
        result = registry.execute("files-main", "read", {"root_id": "control", "path": "README.md"})
        self.assertTrue(result.success)
        self.assertIn("woddi-ai-control", result.data.get("content", ""))

    def test_auth_manager_verifies_default_users(self) -> None:
        admin = auth_manager.verify_credentials("admin", "admin")
        user = auth_manager.verify_credentials("user", "user")
        self.assertIsNotNone(admin)
        self.assertIsNotNone(user)
        self.assertEqual(admin.role, "admin")
        self.assertEqual(user.role, "user")
        self.assertEqual(user.persona_id, "default")

    def test_cli_prerequisites_include_control_configs(self) -> None:
        report = _build_prerequisite_report(argparse.Namespace(systemd="none"))
        names = {item["name"] for item in report.get("checks", [])}
        self.assertIn("file_files_sources.json", names)
        self.assertIn("file_mcps.json", names)
        self.assertIn("file_passwd.json", names)
        self.assertIn("file_default.md", names)


if __name__ == "__main__":
    unittest.main()
