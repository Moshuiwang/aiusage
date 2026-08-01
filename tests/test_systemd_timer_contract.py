from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SystemdTimerContractTests(unittest.TestCase):
    def test_pusher_timer_has_a_persistent_future_calendar_schedule(self) -> None:
        timer = (ROOT / "deploy" / "systemd-user" / "ai-usage-pusher.timer").read_text(encoding="utf-8")

        self.assertIn("OnCalendar=*:0/30", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("AccuracySec=1min", timer)
        self.assertNotIn("OnUnitActiveSec", timer)
        self.assertNotRegex(timer, r"(?m)^Unit=")

    def test_biai_drop_in_replaces_monotonic_trigger_without_changing_service_mapping(self) -> None:
        drop_in = (ROOT / "deploy" / "systemd" / "ai-usage-pusher-calendar.conf").read_text(encoding="utf-8")

        reset_index = drop_in.index("OnUnitActiveSec=\n")
        calendar_index = drop_in.index("OnCalendar=*:0/30")
        self.assertLess(reset_index, calendar_index)
        self.assertIn("Persistent=true", drop_in)
        self.assertIn("AccuracySec=1min", drop_in)
        self.assertNotRegex(drop_in, r"(?m)^Unit=")

    def test_biai_manifest_preserves_all_five_same_basename_service_mappings(self) -> None:
        manifest = json.loads(
            (ROOT / "deploy" / "systemd" / "biai-pusher-timers.json").read_text(encoding="utf-8")
        )
        expected_timers = {
            "ai-usage-pusher-linux-biai-ec2-user.timer",
            "ai-usage-pusher-linux-biai-wangANT.timer",
            "ai-usage-pusher-linux-biai-wangDS.timer",
            "ai-usage-pusher-linux-biai-wangzp.timer",
            "ai-usage-pusher-linux-wang.timer",
        }

        self.assertEqual(set(manifest["timers"]), expected_timers)
        for timer in manifest["timers"]:
            self.assertEqual(manifest["timers"][timer], timer.removesuffix(".timer") + ".service")


if __name__ == "__main__":
    unittest.main()
