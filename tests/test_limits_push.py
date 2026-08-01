from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_usage_widget.limits_push import push_limits_payload


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"status":"accepted"}'


class LimitsPushTests(unittest.TestCase):
    def test_push_uses_product_user_agent_instead_of_python_default(self) -> None:
        captured = []

        def fake_urlopen(req, timeout):
            captured.append((req, timeout))
            return _Response()

        with patch("ai_usage_widget.limits_push.request.urlopen", side_effect=fake_urlopen):
            response = push_limits_payload(
                "https://aiusage.example/ingest-limits",
                "test-token",
                {"limits": []},
                timeout=3.0,
            )

        self.assertEqual(response, {"status": "accepted"})
        self.assertEqual(len(captured), 1)
        req, timeout = captured[0]
        self.assertEqual(timeout, 3.0)
        self.assertEqual(req.get_header("User-agent"), "AIUsagePusher/1.0")


if __name__ == "__main__":
    unittest.main()
