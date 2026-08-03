from __future__ import annotations

import unittest

from ai_usage_widget import mswusage_codex, version_contract


FAKE_TOKEN = "sk-ant-api03-FAKEfakeFAKEfake0123456789"


# 服务端半边（状态词表、compareVersions、wire 校验与脱敏、四态判定、健康读模型）
# 已随 #74 迁到 Worker：`version-contract.test.ts` / `version-contract-decision.test.ts` /
# `version_read_surface.test.ts` / `version-contract-doc.test.ts`，owner 是
# `cloudflare/native-worker/src/version-contract.ts`。Python 只保留采集端自报的出站自检。


class TestLocalCollectorRelease(unittest.TestCase):
    def test_local_release_is_a_valid_wire_block(self) -> None:
        block = version_contract.local_collector_release(config_schema_version=1)

        self.assertEqual(block["collector_version"], version_contract.COLLECTOR_VERSION)
        self.assertEqual(block["parser_schema_version"], version_contract.COLLECTOR_PARSER_SCHEMA_VERSION)
        self.assertEqual(block["release_channel"], "stable")
        self.assertEqual(block["last_upgrade"], {"status": "never"})
        normalized = version_contract.normalize_collector_release(block)
        self.assertEqual(normalized["collector_version"], version_contract.COLLECTOR_VERSION)

    def test_local_release_rejects_unsafe_overrides_before_they_leave_the_device(self) -> None:
        with self.assertRaises(version_contract.VersionContractError):
            version_contract.local_collector_release(config_schema_version=1, build_sha=FAKE_TOKEN)

    def test_local_release_without_any_config_input_is_still_a_valid_block(self) -> None:
        block = version_contract.local_collector_release()

        self.assertNotIn("config_schema_version", block)
        self.assertEqual(block["collector_version"], version_contract.COLLECTOR_VERSION)
        self.assertIsNotNone(version_contract.normalize_collector_release(block))

    def test_parser_schema_version_stays_aligned_with_the_real_parser(self) -> None:
        self.assertEqual(
            version_contract.COLLECTOR_PARSER_SCHEMA_VERSION,
            mswusage_codex.PARSER_SCHEMA_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
