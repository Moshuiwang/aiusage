from __future__ import annotations

import unittest
from pathlib import Path

from ai_usage_widget.macos_launchd import ensure_agent_loaded


class LaunchdActivationTests(unittest.TestCase):
    def test_missing_agent_is_bootstrapped_kickstarted_and_verified(self) -> None:
        calls: list[list[str]] = []
        responses = iter([1, 0, 0, 0])

        def runner(argv):
            calls.append(list(argv))
            return next(responses)

        result = ensure_agent_loaded(
            Path("/tmp/com.example.agent.plist"),
            "com.example.agent",
            user_id=501,
            command_runner=runner,
        )

        self.assertTrue(result["bootstrapped"])
        self.assertEqual(
            calls,
            [
                ["launchctl", "print", "gui/501/com.example.agent"],
                ["launchctl", "bootstrap", "gui/501", "/tmp/com.example.agent.plist"],
                ["launchctl", "kickstart", "-k", "gui/501/com.example.agent"],
                ["launchctl", "print", "gui/501/com.example.agent"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
