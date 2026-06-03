from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.codex_limits_provider import (
    CodexProviderError,
    CodexWhamProvider,
    load_codex_access_token,
)


FIXTURES = Path(__file__).parent / "fixtures"


class FakeWhamHTTPClient:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {
            "observed_at": "2026-06-03T10:00:00+08:00",
            "primary_window": {
                "used_percent": 41.2,
                "remaining_percent": 58.8,
                "reset_at": "2026-06-03T14:00:00+08:00",
                "window_duration_minutes": 300,
                "status": "ok",
            },
            "secondary_window": {
                "used_percent": 27.5,
                "remaining_percent": 72.5,
                "reset_at": "2026-06-08T00:00:00+08:00",
                "window_duration_minutes": 10080,
                "status": "ok",
            },
        }
        self.last_url = ""
        self.last_headers: dict[str, str] = {}

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict]:
        self.last_url = url
        self.last_headers = headers
        return self.status_code, self.payload


class TestCodexWhamAdapter(unittest.TestCase):
    def test_load_codex_access_token_from_explicit_fixture_path(self) -> None:
        token = load_codex_access_token(str(FIXTURES / "codex_auth_sample.json"))

        self.assertEqual(token, "codex-access-token-fixture")

    def test_missing_auth_file_maps_to_missing_credentials_without_secret_text(self) -> None:
        with self.assertRaises(CodexProviderError) as ctx:
            load_codex_access_token("/tmp/ai-usage-widget-missing-codex-auth.json")

        self.assertEqual(ctx.exception.error_type, "missing_credentials")
        self.assertNotIn("token", str(ctx.exception).lower())

    def test_wham_provider_uses_bearer_token_and_parses_windows(self) -> None:
        http_client = FakeWhamHTTPClient()
        provider = CodexWhamProvider(
            auth_file=str(FIXTURES / "codex_auth_sample.json"),
            http_client=http_client,
        )

        windows = provider.collect()

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].provider, "codex")
        self.assertEqual(windows[0].source_type, "runtime_api")
        self.assertIn("/backend-api/wham/usage", http_client.last_url)
        self.assertEqual(http_client.last_headers["Authorization"], "Bearer codex-access-token-fixture")

    def test_wham_provider_maps_auth_failure_to_unauthorized(self) -> None:
        provider = CodexWhamProvider(
            auth_file=str(FIXTURES / "codex_auth_sample.json"),
            http_client=FakeWhamHTTPClient(status_code=401, payload={"error": "bad token"}),
        )

        with self.assertRaises(CodexProviderError) as ctx:
            provider.collect()

        self.assertEqual(ctx.exception.error_type, "unauthorized")
        self.assertNotIn("codex-access-token-fixture", str(ctx.exception))

    def test_auth_loader_rejects_missing_token_shape(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("{}")

            with self.assertRaises(CodexProviderError) as ctx:
                load_codex_access_token(path)

            self.assertEqual(ctx.exception.error_type, "missing_credentials")
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
