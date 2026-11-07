"""#287：采集端自动识别账户资料（指纹 + 展示名 + 套餐），不需要用户手工维护账户清单。

输入全部是临时文件；不碰真实 HOME。断言除了「识别出了什么」，也断言「凭据原文没有漏进结果」。
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.account_fingerprint import (
    AccountProfile,
    claude_account_profile,
    codex_account_profile,
    compute_account_fingerprint,
    normalize_claude_plan,
)


def _jwt(claims: dict) -> str:
    def seg(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg(claims)}.signature-not-checked"


class _TempJson:
    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(self.payload, handle)
        handle.close()
        self.path = Path(handle.name)
        return self.path

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


CLAUDE_CONFIG = {
    "oauthAccount": {
        "accountUuid": "11111111-1111-1111-1111-111111111111",
        "displayName": "Zhipeng",
        "emailAddress": "someone@example.com",
        "organizationType": "claude_max",
        "organizationRateLimitTier": "default_claude_max_5x",
    }
}


class TestClaudeAccountProfile(unittest.TestCase):
    def test_reads_fingerprint_label_and_plan_from_profile(self) -> None:
        with _TempJson(CLAUDE_CONFIG) as path:
            profile = claude_account_profile(path)
        self.assertEqual(
            profile,
            AccountProfile(
                fingerprint=compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111"),
                label="Zhipeng",
                plan="max_5x",
            ),
        )

    def test_profile_never_contains_email(self) -> None:
        with _TempJson(CLAUDE_CONFIG) as path:
            profile = claude_account_profile(path)
        self.assertNotIn("someone@example.com", json.dumps(profile.to_payload()))

    def test_plan_comes_from_profile_tier_not_stale_credential_cache(self) -> None:
        """TZ 实测：.credentials.json 的 subscriptionType=pro 是陈旧值，账户资料是 max_5x。"""
        with _TempJson(CLAUDE_CONFIG) as path:
            (path.parent / ".credentials.json")  # 刻意不读这份文件
            profile = claude_account_profile(path)
        self.assertEqual(profile.plan, "max_5x")

    def test_display_name_that_looks_like_email_is_not_uploaded(self) -> None:
        config = {"oauthAccount": {"accountUuid": "u-1", "displayName": "someone@example.com"}}
        with _TempJson(config) as path:
            profile = claude_account_profile(path)
        self.assertIsNone(profile.label)
        self.assertNotIn("@", json.dumps(profile.to_payload()))

    def test_missing_tier_keeps_fingerprint_with_unknown_plan(self) -> None:
        config = {"oauthAccount": {"accountUuid": "u-1", "displayName": "A"}}
        with _TempJson(config) as path:
            profile = claude_account_profile(path)
        self.assertEqual(profile.fingerprint, compute_account_fingerprint("claude", "u-1"))
        self.assertIsNone(profile.plan)

    def test_missing_account_uuid_returns_none(self) -> None:
        with _TempJson({"oauthAccount": {"displayName": "A"}}) as path:
            self.assertIsNone(claude_account_profile(path))

    def test_unreadable_file_returns_none(self) -> None:
        self.assertIsNone(claude_account_profile("/nonexistent/claude.json"))


class TestClaudePlanNormalization(unittest.TestCase):
    def test_known_tiers(self) -> None:
        cases = {
            "default_claude_max_5x": "max_5x",
            "default_claude_max_20x": "max_20x",
            "default_claude_ai": "pro",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_claude_plan(raw), expected)
        self.assertEqual(len(cases), 3)

    def test_unknown_tier_is_kept_without_prefix_not_guessed(self) -> None:
        self.assertEqual(normalize_claude_plan("default_claude_team_premium"), "team_premium")

    def test_blank_tier_is_none(self) -> None:
        self.assertIsNone(normalize_claude_plan(""))
        self.assertIsNone(normalize_claude_plan(None))


class TestCodexAccountProfile(unittest.TestCase):
    def _auth(self, claims: dict) -> dict:
        return {
            "tokens": {
                "account_id": "33333333-3333-3333-3333-333333333333",
                "access_token": "secret-access-token-value",
                "refresh_token": "secret-refresh-token-value",
                "id_token": _jwt(claims),
            }
        }

    def test_reads_fingerprint_label_and_plan(self) -> None:
        claims = {"name": "Em", "email": "em@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}
        with _TempJson(self._auth(claims)) as path:
            profile = codex_account_profile(path)
        self.assertEqual(
            profile,
            AccountProfile(
                fingerprint=compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333"),
                label="Em",
                plan="pro",
            ),
        )

    def test_profile_never_contains_tokens_or_email(self) -> None:
        claims = {"name": "Em", "email": "em@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}
        with _TempJson(self._auth(claims)) as path:
            text = json.dumps(codex_account_profile(path).to_payload())
        for secret in ("secret-access-token-value", "secret-refresh-token-value", "em@example.com"):
            self.assertNotIn(secret, text)

    def test_codex_name_that_looks_like_email_is_not_uploaded(self) -> None:
        claims = {"name": "em@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}
        with _TempJson(self._auth(claims)) as path:
            profile = codex_account_profile(path)
        self.assertIsNone(profile.label)
        self.assertEqual(profile.plan, "pro")

    def test_malformed_id_token_keeps_fingerprint_without_plan(self) -> None:
        auth = {"tokens": {"account_id": "acc-1", "id_token": "not-a-jwt"}}
        with _TempJson(auth) as path:
            profile = codex_account_profile(path)
        self.assertEqual(profile, AccountProfile(compute_account_fingerprint("codex", "acc-1"), None, None))


class TestPayloadShape(unittest.TestCase):
    def test_payload_omits_missing_fields(self) -> None:
        self.assertEqual(AccountProfile("fp:claude:abc", None, None).to_payload(), {"fingerprint": "fp:claude:abc"})
        self.assertEqual(
            AccountProfile("fp:claude:abc", "A", "max_5x").to_payload(),
            {"fingerprint": "fp:claude:abc", "label": "A", "plan": "max_5x"},
        )


if __name__ == "__main__":
    unittest.main()
