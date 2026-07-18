from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.claude_limits_provider import (
    ClaudeOAuthProvider,
    ClaudeProviderError,
    load_claude_access_token,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingHTTPClient:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload
        self.calls: list[dict] = []

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict]:
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.status_code, self.payload


class TestClaudeOAuthAdapter(unittest.TestCase):
    def test_load_claude_access_token_from_explicit_fixture_path(self) -> None:
        token = load_claude_access_token(str(FIXTURES / "claude_auth_sample.json"))

        self.assertEqual(token, "claude-test-access-token")

    def test_load_claude_access_token_from_current_claude_code_shape(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump({"claudeAiOauth": {"accessToken": "current-test-access-token"}}, handle)
            handle.flush()

            token = load_claude_access_token(handle.name)

        self.assertEqual(token, "current-test-access-token")

    def test_missing_auth_file_maps_to_missing_credentials_without_secret_text(self) -> None:
        with self.assertRaises(ClaudeProviderError) as caught:
            load_claude_access_token("/tmp/not-a-real-claude-token-secret.json")

        self.assertEqual(caught.exception.error_type, "missing_credentials")
        self.assertNotIn("secret", str(caught.exception).lower())

    def test_oauth_provider_uses_bearer_token_and_parses_windows(self) -> None:
        payload = json.loads((FIXTURES / "claude_oauth_usage.json").read_text(encoding="utf-8"))
        http_client = RecordingHTTPClient(200, payload)

        windows = ClaudeOAuthProvider(
            auth_file=str(FIXTURES / "claude_auth_sample.json"),
            usage_url="https://example.invalid/claude/usage",
            http_client=http_client,
            timeout=7.5,
        ).collect()

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.source_type for window in windows], ["oauth_usage_api", "oauth_usage_api"])
        self.assertEqual(http_client.calls[0]["url"], "https://example.invalid/claude/usage")
        self.assertEqual(http_client.calls[0]["headers"]["Authorization"], "Bearer claude-test-access-token")
        self.assertEqual(http_client.calls[0]["headers"]["Accept"], "application/json")
        self.assertEqual(http_client.calls[0]["timeout"], 7.5)

    def test_oauth_provider_maps_auth_failure_to_unauthorized(self) -> None:
        http_client = RecordingHTTPClient(403, {"error": "denied"})

        with self.assertRaises(ClaudeProviderError) as caught:
            ClaudeOAuthProvider(
                auth_file=str(FIXTURES / "claude_auth_sample.json"),
                usage_url="https://example.invalid/claude/usage",
                http_client=http_client,
            ).collect()

        self.assertEqual(caught.exception.error_type, "unauthorized")

    def test_auth_loader_rejects_missing_token_shape(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump({"oauth": {"refresh_token": "do-not-use"}}, handle)
            handle.flush()

            with self.assertRaises(ClaudeProviderError) as caught:
                load_claude_access_token(handle.name)

        self.assertEqual(caught.exception.error_type, "missing_credentials")


if __name__ == "__main__":
    unittest.main()
