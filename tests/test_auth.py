from __future__ import annotations

import unittest

from ai_usage_widget.auth import TokenAuthenticator, parse_token_specs


class TestTokenAuthenticator(unittest.TestCase):
    def test_accepts_any_active_token_from_labeled_specs(self) -> None:
        authenticator = TokenAuthenticator.from_values(
            primary_token="legacy-token",
            token_specs="ai:token-ai,biai:token-biai",
        )

        self.assertTrue(authenticator.is_required)
        self.assertTrue(authenticator.verify("legacy-token"))
        self.assertTrue(authenticator.verify("token-ai"))
        self.assertTrue(authenticator.verify("token-biai"))
        self.assertFalse(authenticator.verify("bad-token"))

    def test_parse_token_specs_does_not_keep_empty_values(self) -> None:
        parsed = parse_token_specs("ai:token-ai,, plain-token ,bad-label:")

        self.assertEqual(parsed, ["token-ai", "plain-token"])


if __name__ == "__main__":
    unittest.main()
