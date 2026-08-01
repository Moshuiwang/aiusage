from __future__ import annotations

import unittest

from ai_usage_widget import mswusage_codex, version_contract


FAKE_TOKEN = "sk-ant-api03-FAKEfakeFAKEfake0123456789"
FAKE_PATH = "/home/wangzp/.config/ai-usage/config.local.json"


class TestVersionStateVocabulary(unittest.TestCase):
    def test_issue_58_four_states_are_the_declared_contract(self) -> None:
        self.assertEqual(
            version_contract.VERSION_STATES,
            ("current", "update_available", "unsupported", "rollback_available"),
        )

    def test_unknown_is_a_separate_degradation_state_not_one_of_the_four(self) -> None:
        self.assertEqual(version_contract.VERSION_STATE_UNKNOWN, "unknown")
        self.assertNotIn(version_contract.VERSION_STATE_UNKNOWN, version_contract.VERSION_STATES)
        self.assertEqual(
            set(version_contract.ALL_VERSION_STATES),
            set(version_contract.VERSION_STATES) | {"unknown"},
        )

    def test_every_state_has_a_deterministic_severity_rank(self) -> None:
        ranks = [version_contract.VERSION_STATE_SEVERITY[state] for state in version_contract.ALL_VERSION_STATES]
        self.assertEqual(len(set(ranks)), len(ranks))
        self.assertLess(
            version_contract.VERSION_STATE_SEVERITY["unsupported"],
            version_contract.VERSION_STATE_SEVERITY["rollback_available"],
        )
        self.assertLess(
            version_contract.VERSION_STATE_SEVERITY["rollback_available"],
            version_contract.VERSION_STATE_SEVERITY["update_available"],
        )
        self.assertLess(
            version_contract.VERSION_STATE_SEVERITY["update_available"],
            version_contract.VERSION_STATE_SEVERITY["current"],
        )


class TestVersionCompare(unittest.TestCase):
    def test_compare_versions_orders_semver_numerically_not_lexically(self) -> None:
        self.assertEqual(version_contract.compare_versions("0.10.0", "0.9.0"), 1)
        self.assertEqual(version_contract.compare_versions("0.9.0", "0.10.0"), -1)
        self.assertEqual(version_contract.compare_versions("1.2.3", "1.2.3"), 0)

    def test_prerelease_sorts_before_its_release(self) -> None:
        self.assertEqual(version_contract.compare_versions("1.2.3-beta.1", "1.2.3"), -1)
        self.assertEqual(version_contract.compare_versions("1.2.3", "1.2.3-beta.1"), 1)

    def test_prerelease_numbers_compare_numerically_not_lexically(self) -> None:
        self.assertEqual(version_contract.compare_versions("0.4.0-beta.2", "0.4.0-beta.10"), -1)
        self.assertEqual(version_contract.compare_versions("0.4.0-beta.10", "0.4.0-beta.2"), 1)
        self.assertEqual(version_contract.compare_versions("0.4.0-beta.9", "0.4.0-beta.10"), -1)

    def test_prerelease_precedence_follows_semver_rules(self) -> None:
        self.assertEqual(version_contract.compare_versions("1.0.0-alpha", "1.0.0-beta"), -1)
        self.assertEqual(version_contract.compare_versions("1.0.0-alpha", "1.0.0-alpha.1"), -1)
        self.assertEqual(version_contract.compare_versions("1.0.0-1", "1.0.0-alpha"), -1)

    def test_build_metadata_does_not_affect_precedence(self) -> None:
        self.assertEqual(version_contract.compare_versions("1.2.3+build.9", "1.2.3"), 0)
        self.assertEqual(version_contract.compare_versions("1.2.3-beta.1+build.9", "1.2.3-beta.1"), 0)

    def test_a_beta_channel_device_behind_the_beta_target_is_not_called_ahead(self) -> None:
        result = version_contract.evaluate_collector_release(
            version_contract.normalize_collector_release({"collector_version": "0.4.0-beta.2"}),
            policy=version_contract.VersionPolicy(
                min_supported_collector_version="0.2.0",
                target_collector_version="0.4.0-beta.10",
            ),
        )

        self.assertEqual(result["state"], "update_available")


class TestCollectorReleaseNormalization(unittest.TestCase):
    def test_full_release_block_is_flattened_into_canonical_fields(self) -> None:
        normalized = version_contract.normalize_collector_release(
            {
                "collector_version": "0.3.0",
                "config_schema_version": 1,
                "parser_schema_version": 2,
                "release_channel": "stable",
                "build_sha": "0a1b2c3d4e5",
                "last_upgrade": {
                    "status": "succeeded",
                    "from_version": "0.2.0",
                    "to_version": "0.3.0",
                    "finished_at": "2026-08-01T09:00:00+08:00",
                },
            }
        )

        self.assertEqual(
            normalized,
            {
                "collector_version": "0.3.0",
                "config_schema_version": 1,
                "parser_schema_version": 2,
                "release_channel": "stable",
                "build_sha": "0a1b2c3d4e5",
                "last_upgrade_status": "succeeded",
                "last_upgrade_from_version": "0.2.0",
                "last_upgrade_to_version": "0.3.0",
                "last_upgrade_finished_at": "2026-08-01T09:00:00+08:00",
            },
        )

    def test_absent_block_degrades_to_none_instead_of_raising(self) -> None:
        self.assertIsNone(version_contract.normalize_collector_release(None))

    def test_partial_block_keeps_known_fields_and_nulls_the_rest(self) -> None:
        normalized = version_contract.normalize_collector_release({"collector_version": "0.3.0"})

        self.assertEqual(normalized["collector_version"], "0.3.0")
        self.assertIsNone(normalized["build_sha"])
        self.assertIsNone(normalized["last_upgrade_status"])
        self.assertEqual(set(normalized), set(version_contract.COLLECTOR_VERSION_FIELDS))

    def test_non_object_block_is_an_explicit_contract_error(self) -> None:
        with self.assertRaises(version_contract.VersionContractError) as ctx:
            version_contract.normalize_collector_release([])
        self.assertEqual(ctx.exception.field, "collector_release")

    def test_unknown_key_is_rejected_so_extra_data_cannot_ride_along(self) -> None:
        with self.assertRaises(version_contract.VersionContractError) as ctx:
            version_contract.normalize_collector_release({"collector_version": "0.3.0", "auth_token": "x"})
        self.assertIn("auth_token", str(ctx.exception))

    def test_a_credential_shaped_unknown_key_is_redacted_instead_of_echoed(self) -> None:
        for key in (
            FAKE_TOKEN,
            FAKE_PATH,
            "x" * 80,
            # 纯字母数字、长度 <= 32 的凭据形态：以前整类漏过白名单，被原样写进 400 响应体和日志。
            "AKIAIOSFODNN7EXAMPLE",              # AWS Access Key ID
            "xoxbXXXXXXXXXXXXXXXXXXXXXXXX",      # Slack bot token
            "AIzaSyDUMMYdummyDUMMYdummy1234",    # Google API key
            "deadbeefcafe1234deadbeefcafe1234",  # 十六进制密钥
            "0123456789abcdef0123",              # 纯小写十六进制
        ):
            with self.subTest(key=key):
                with self.assertRaises(version_contract.VersionContractError) as ctx:
                    version_contract.normalize_collector_release({key: "x"})
                self.assertNotIn(key, str(ctx.exception))
                self.assertNotIn(key, ctx.exception.field)

    def test_a_plain_field_name_is_still_echoed_so_the_error_stays_actionable(self) -> None:
        for key in ("auth_token", "surprise", "last_upgrade_status"):
            with self.subTest(key=key):
                with self.assertRaises(version_contract.VersionContractError) as ctx:
                    version_contract.normalize_collector_release({key: "x"})
                self.assertIn(key, str(ctx.exception))

    def test_a_trailing_newline_cannot_smuggle_itself_through_the_whitelist(self) -> None:
        """`$` 在末尾单个 `\\n` 前也会匹配，白名单声称的严格性因此不成立。

        后果不是形式问题：带换行的版本号会原样落进 `collection_runs.collector_version`
        和 `/api/summary` 的版本块，同一个版本在库里裂成两个字符串，
        并且会被裸拼进不兼容时的错误信息。
        """
        for raw in (
            {"collector_version": "0.3.0\n"},
            {"build_sha": "cafebabe\n"},
            {"last_upgrade": {"finished_at": "2026-08-01T09:00:00+08:00\n"}},
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(version_contract.VersionContractError):
                    version_contract.normalize_collector_release(raw)

    def test_a_credential_shaped_unknown_key_inside_last_upgrade_is_also_redacted(self) -> None:
        with self.assertRaises(version_contract.VersionContractError) as ctx:
            version_contract.normalize_collector_release({"last_upgrade": {FAKE_TOKEN: "x"}})

        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))
        self.assertNotIn(FAKE_TOKEN, ctx.exception.field)

    def test_token_shaped_value_is_rejected_and_never_echoed_back(self) -> None:
        with self.assertRaises(version_contract.VersionContractError) as ctx:
            version_contract.normalize_collector_release({"collector_version": FAKE_TOKEN})

        self.assertEqual(ctx.exception.field, "collector_release.collector_version")
        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))

    def test_absolute_path_value_is_rejected_and_never_echoed_back(self) -> None:
        for field, raw in [
            ("collector_release.build_sha", {"build_sha": FAKE_PATH}),
            ("collector_release.release_channel", {"release_channel": FAKE_PATH}),
            ("collector_release.collector_version", {"collector_version": FAKE_PATH}),
        ]:
            with self.subTest(field=field):
                with self.assertRaises(version_contract.VersionContractError) as ctx:
                    version_contract.normalize_collector_release(raw)
                self.assertEqual(ctx.exception.field, field)
                self.assertNotIn(FAKE_PATH, str(ctx.exception))

    def test_release_channel_is_restricted_to_declared_channels(self) -> None:
        self.assertEqual(version_contract.RELEASE_CHANNELS, ("stable", "beta", "dev"))
        with self.assertRaises(version_contract.VersionContractError):
            version_contract.normalize_collector_release({"release_channel": "prod"})

    def test_last_upgrade_status_is_restricted_to_declared_results(self) -> None:
        self.assertEqual(
            version_contract.LAST_UPGRADE_STATUSES,
            ("never", "succeeded", "failed", "rolled_back"),
        )
        with self.assertRaises(version_contract.VersionContractError) as ctx:
            version_contract.normalize_collector_release({"last_upgrade": {"status": "maybe"}})
        self.assertEqual(ctx.exception.field, "collector_release.last_upgrade.status")


class TestCollectorReleaseEvaluation(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = version_contract.VersionPolicy(
            min_supported_collector_version="0.2.0",
            target_collector_version="0.4.0",
            min_supported_config_schema_version=1,
            min_supported_parser_schema_version=2,
        )

    def _evaluate(self, **release):
        block = {"collector_version": "0.4.0", "config_schema_version": 1, "parser_schema_version": 2}
        block.update(release)
        return version_contract.evaluate_collector_release(
            version_contract.normalize_collector_release(block),
            policy=self.policy,
        )

    def test_missing_release_is_unknown_and_not_silently_treated_as_compliant(self) -> None:
        result = version_contract.evaluate_collector_release(None, policy=self.policy)

        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "collector_release_missing")
        self.assertIsNone(result["collector_version"])
        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])

    def test_missing_collector_version_inside_block_is_still_unknown(self) -> None:
        result = self._evaluate(collector_version=None)

        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "collector_version_missing")
        self.assertFalse(result["verified"])

    def test_version_at_target_is_current(self) -> None:
        result = self._evaluate()

        self.assertEqual(result["state"], "current")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["verified"])

    def test_version_behind_target_but_above_minimum_is_update_available(self) -> None:
        result = self._evaluate(collector_version="0.3.0")

        self.assertEqual(result["state"], "update_available")
        self.assertEqual(result["reason"], "collector_version_behind_target")
        self.assertTrue(result["accepted"])

    def test_version_below_minimum_is_unsupported_and_not_accepted(self) -> None:
        result = self._evaluate(collector_version="0.1.9")

        self.assertEqual(result["state"], "unsupported")
        self.assertEqual(result["reason"], "collector_version_below_minimum")
        self.assertFalse(result["accepted"])

    def test_parser_schema_below_minimum_is_unsupported(self) -> None:
        result = self._evaluate(parser_schema_version=1)

        self.assertEqual(result["state"], "unsupported")
        self.assertEqual(result["reason"], "parser_schema_version_below_minimum")
        self.assertFalse(result["accepted"])

    def test_failed_last_upgrade_with_known_previous_version_is_rollback_available(self) -> None:
        result = self._evaluate(
            collector_version="0.4.0",
            last_upgrade={"status": "failed", "from_version": "0.3.0", "to_version": "0.4.0"},
        )

        self.assertEqual(result["state"], "rollback_available")
        self.assertEqual(result["reason"], "last_upgrade_failed")
        self.assertEqual(result["rollback_target_version"], "0.3.0")
        self.assertTrue(result["accepted"])

    def test_version_ahead_of_target_is_rollback_available_to_target(self) -> None:
        result = self._evaluate(collector_version="0.5.0")

        self.assertEqual(result["state"], "rollback_available")
        self.assertEqual(result["reason"], "collector_version_ahead_of_target")
        self.assertEqual(result["rollback_target_version"], "0.4.0")

    def test_unsupported_wins_over_rollback_and_update(self) -> None:
        result = self._evaluate(
            collector_version="0.1.0",
            last_upgrade={"status": "failed", "from_version": "0.0.9"},
        )

        self.assertEqual(result["state"], "unsupported")

    def test_evaluation_always_reports_the_policy_it_used(self) -> None:
        result = self._evaluate()

        self.assertEqual(result["min_supported_collector_version"], "0.2.0")
        self.assertEqual(result["target_collector_version"], "0.4.0")


class TestVersionHealthReadModel(unittest.TestCase):
    def _entry(self, source_id: str, state: str, **extra):
        entry = {
            "source_id": source_id,
            "display_name": f"{source_id} display",
            "status": "ok",
            "observed_at": "2026-08-01T10:00:00+08:00",
        }
        entry.update(extra)
        if state is not None:
            entry["version"] = {
                "state": state,
                "collector_version": "0.3.0",
                "compatible": state != "unsupported",
                "reason": "test",
            }
        return entry

    def test_needs_attention_lists_every_outdated_or_incompatible_source(self) -> None:
        health = version_contract.build_version_health(
            [
                self._entry("b-ok", "current"),
                self._entry("a-old", "update_available"),
                self._entry("c-bad", "unsupported"),
                self._entry("d-none", None),
            ]
        )

        self.assertEqual(
            [row["source_id"] for row in health["needs_attention"]],
            ["c-bad", "a-old", "d-none"],
        )

    def test_ordering_is_deterministic_by_severity_then_source_id(self) -> None:
        entries = [
            self._entry("z-update", "update_available"),
            self._entry("a-update", "update_available"),
            self._entry("z-unsupported", "unsupported"),
            self._entry("a-unsupported", "unsupported"),
            self._entry("m-rollback", "rollback_available"),
        ]
        forward = version_contract.build_version_health(entries)
        reversed_health = version_contract.build_version_health(list(reversed(entries)))

        self.assertEqual(
            [row["source_id"] for row in forward["needs_attention"]],
            ["a-unsupported", "z-unsupported", "m-rollback", "a-update", "z-update"],
        )
        self.assertEqual(forward["needs_attention"], reversed_health["needs_attention"])

    def test_counts_cover_every_state_even_when_zero(self) -> None:
        health = version_contract.build_version_health([self._entry("only", "current")])

        self.assertEqual(
            health["counts"],
            {
                "current": 1,
                "update_available": 0,
                "unsupported": 0,
                "rollback_available": 0,
                "unknown": 0,
            },
        )

    def test_server_block_is_always_reported(self) -> None:
        health = version_contract.build_version_health([])

        self.assertEqual(set(health["server"]), set(version_contract.SERVER_VERSION_FIELDS))
        self.assertEqual(health["counts"], {state: 0 for state in version_contract.ALL_VERSION_STATES})
        self.assertEqual(health["needs_attention"], [])


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
