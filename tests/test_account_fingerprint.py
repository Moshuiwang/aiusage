from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.account_fingerprint import (
    claude_account_fingerprint,
    codex_account_fingerprint,
    compute_account_fingerprint,
    read_claude_stable_account_id,
    read_codex_stable_account_id,
)


FIXTURES = Path(__file__).parent / "fixtures"


class TestComputeAccountFingerprint(unittest.TestCase):
    def test_same_account_same_provider_is_deterministic_across_calls(self) -> None:
        """同一账户在不同机器上算出来的指纹必须相同——机器身份不参与计算。"""
        fp_machine_a = compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111")
        fp_machine_b = compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111")
        self.assertEqual(fp_machine_a, fp_machine_b)

    def test_different_account_id_yields_different_fingerprint(self) -> None:
        fp_a = compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111")
        fp_b = compute_account_fingerprint("claude", "99999999-9999-9999-9999-999999999999")
        self.assertNotEqual(fp_a, fp_b)

    def test_different_provider_same_account_id_yields_different_fingerprint(self) -> None:
        """provider 必须参与哈希计算本身，不能只靠输出里的 ``fp:<provider>:`` 前缀撞出「看起来不同」。

        只比较完整字符串是恒真断言的变种：``fp:claude:`` 和 ``fp:codex:`` 前缀本身就不同，
        字符串必然不相等，测试却检查不到 provider 到底有没有真的进哈希摘要——所以这里
        单独取出摘要（去掉 provider 前缀）再比较。
        """
        fp_claude = compute_account_fingerprint("claude", "same-id")
        fp_codex = compute_account_fingerprint("codex", "same-id")
        digest_claude = fp_claude.rsplit(":", 1)[-1]
        digest_codex = fp_codex.rsplit(":", 1)[-1]
        self.assertNotEqual(digest_claude, digest_codex)

    def test_fingerprint_format_is_stable(self) -> None:
        fp = compute_account_fingerprint("codex", "acct-123")
        self.assertTrue(fp.startswith("fp:codex:"))
        hex_part = fp.split(":", 2)[2]
        self.assertEqual(len(hex_part), 24)
        int(hex_part, 16)  # 必须是合法十六进制

    def test_golden_codex_fingerprint_matches_independently_computed_value(self) -> None:
        """#181 协调者独立复算的 golden：跟本函数的实现完全解耦——不管内部怎么改哈希材料的
        拼法，只要最终字符串跟这条字面值不一致就必须红。计算方式见 salt 常量 + 下面这行等价
        Python：``"fp:codex:" + hashlib.sha256(b"aiusage-account-v1:codex:33333333-3333-3333-3333-333333333333").hexdigest()[:24]``。
        """
        self.assertEqual(
            compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333"),
            "fp:codex:ad5d4ce6324ab7e5a0909ba8",
        )

    def test_golden_claude_fingerprint_matches_independently_computed_value(self) -> None:
        """字面 golden，在测试之外独立算出（不是从被测函数抠出来的），计算命令：

        python3 -c "
        import hashlib
        material = 'aiusage-account-v1:claude:11111111-1111-1111-1111-111111111111'.encode('utf-8')
        print('fp:claude:' + hashlib.sha256(material).hexdigest()[:24])
        "

        输出：``fp:claude:35f06f61d06d4aa38b8a3b94``。
        """
        self.assertEqual(
            compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111"),
            "fp:claude:35f06f61d06d4aa38b8a3b94",
        )

    def test_fingerprint_is_irreversible_does_not_contain_raw_id(self) -> None:
        raw_id = "super-secret-account-id-marker"
        fp = compute_account_fingerprint("codex", raw_id)
        self.assertNotIn(raw_id, fp)

    def test_provider_is_case_normalized_to_lowercase(self) -> None:
        """provider 大小写不参与"是否同一账户"的判断——调用方（pusher.py/cli.py）现在只传
        小写字面量，但指纹格式（``fp:<provider>:...``）和 Worker 侧的正则
        （``^fp:[a-z0-9_-]+:...``）都要求小写前缀，这里在算指纹之前显式规整，不依赖
        调用方永远传对大小写。golden 值本就是小写，这条测试不改变现有 golden。
        """
        fp_lower = compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333")
        fp_upper = compute_account_fingerprint("CODEX", "33333333-3333-3333-3333-333333333333")
        fp_mixed = compute_account_fingerprint("CoDeX", "33333333-3333-3333-3333-333333333333")
        self.assertEqual(fp_lower, fp_upper)
        self.assertEqual(fp_lower, fp_mixed)
        self.assertTrue(fp_lower.startswith("fp:codex:"))

    def test_rejects_empty_inputs(self) -> None:
        with self.assertRaises(ValueError):
            compute_account_fingerprint("", "acct-123")
        with self.assertRaises(ValueError):
            compute_account_fingerprint("codex", "")


class TestReadClaudeStableAccountId(unittest.TestCase):
    def test_reads_account_uuid_from_oauth_account(self) -> None:
        config = {"oauthAccount": {"accountUuid": "abc-123", "emailAddress": "x@example.com"}}
        self.assertEqual(read_claude_stable_account_id(config), "abc-123")

    def test_returns_none_for_top_level_account_uuid_without_oauth_account(self) -> None:
        """#181 P1-2：只认 ``oauthAccount.accountUuid``，顶层 ``accountUuid`` 不是约定字段，
        不做兼容 fallback（AGENTS.md：不新增旧格式兼容层）。"""
        config = {"accountUuid": "top-level-uuid"}
        self.assertIsNone(read_claude_stable_account_id(config))

    def test_returns_none_when_not_a_dict(self) -> None:
        self.assertIsNone(read_claude_stable_account_id(None))
        self.assertIsNone(read_claude_stable_account_id("not-a-dict"))
        self.assertIsNone(read_claude_stable_account_id([1, 2, 3]))

    def test_returns_none_when_field_missing(self) -> None:
        self.assertIsNone(read_claude_stable_account_id({"oauthAccount": {"emailAddress": "x@example.com"}}))
        self.assertIsNone(read_claude_stable_account_id({}))

    def test_returns_none_when_field_is_blank(self) -> None:
        self.assertIsNone(read_claude_stable_account_id({"oauthAccount": {"accountUuid": "   "}}))


class TestReadCodexStableAccountId(unittest.TestCase):
    def test_reads_account_id_from_tokens(self) -> None:
        auth = {"tokens": {"access_token": "x", "account_id": "acct-999"}}
        self.assertEqual(read_codex_stable_account_id(auth), "acct-999")

    def test_returns_none_for_top_level_account_id_without_tokens(self) -> None:
        """#181 P1-2：只认 ``tokens.account_id``，顶层 ``account_id`` 不是约定字段。"""
        auth = {"account_id": "top-level-acct"}
        self.assertIsNone(read_codex_stable_account_id(auth))

    def test_returns_none_for_nested_account_object(self) -> None:
        """#181 P1-2：``account.id`` 不是约定字段，即便 ``tokens`` 缺失也不兜底读它。"""
        auth = {"account": {"id": "nested-acct"}}
        self.assertIsNone(read_codex_stable_account_id(auth))

    def test_returns_none_for_camel_case_account_id_under_tokens(self) -> None:
        """#181 P1-2：约定字段名固定为 ``account_id``（snake_case），``accountId`` 不是
        约定字段，即便它出现在 ``tokens`` 下也不认。"""
        auth = {"tokens": {"accountId": "camel-case-acct"}}
        self.assertIsNone(read_codex_stable_account_id(auth))

    def test_returns_none_when_missing(self) -> None:
        self.assertIsNone(read_codex_stable_account_id({"tokens": {"access_token": "x"}}))
        self.assertIsNone(read_codex_stable_account_id(None))
        self.assertIsNone(read_codex_stable_account_id({}))


class TestFileBasedFingerprintHelpers(unittest.TestCase):
    """这几个测试专门核对读不到/解析不出时降级为 None，以及输出里不含凭据原文。

    全部走离线 fixture 文件（tests/fixtures/*_account_*_sample.json），
    没有任何一条会碰真实 HOME 目录。
    """

    def test_claude_account_fingerprint_from_fixture_file(self) -> None:
        path = FIXTURES / "claude_account_config_sample.json"
        fp = claude_account_fingerprint(path)
        expected = compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111")
        self.assertEqual(fp, expected)

    def test_claude_account_fingerprint_missing_file_returns_none(self) -> None:
        self.assertIsNone(claude_account_fingerprint(FIXTURES / "does_not_exist_claude.json"))

    def test_claude_account_fingerprint_invalid_json_returns_none(self, ) -> None:
        with self._temp_file("{not valid json") as path:
            self.assertIsNone(claude_account_fingerprint(path))

    def test_claude_account_fingerprint_non_utf8_file_returns_none(self) -> None:
        """docstring 承诺 `_read_json_file` 从不抛异常；非 UTF-8 文件是之前漏掉的绕过路径
        （codereview 发现：只 catch 了 OSError/JSONDecodeError，UnicodeDecodeError 会漏出去，
        在 push-limits 那条没有额外 try/except 的调用路径上会让整次采集报错中断）。
        """
        import tempfile

        fd, name = tempfile.mkstemp(suffix=".json")
        try:
            with open(fd, "wb") as handle:
                handle.write(b"\xff\xfe not valid utf-8 \x80\x81")
            self.assertIsNone(claude_account_fingerprint(name))
            self.assertIsNone(codex_account_fingerprint(name))
        finally:
            Path(name).unlink(missing_ok=True)

    def test_claude_account_fingerprint_does_not_leak_email(self) -> None:
        path = FIXTURES / "claude_account_config_sample.json"
        fp = claude_account_fingerprint(path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertIn("tony@example.com", raw_text)  # fixture 确实带着邮箱
        self.assertNotIn("tony@example.com", fp)  # 但指纹里不能有

    def test_codex_account_fingerprint_from_fixture_file(self) -> None:
        path = FIXTURES / "codex_account_auth_sample.json"
        fp = codex_account_fingerprint(path)
        expected = compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333")
        self.assertEqual(fp, expected)

    def test_codex_account_fingerprint_missing_file_returns_none(self) -> None:
        self.assertIsNone(codex_account_fingerprint(FIXTURES / "does_not_exist_codex.json"))

    def test_codex_account_fingerprint_does_not_leak_refresh_token(self) -> None:
        path = FIXTURES / "codex_account_auth_sample.json"
        fp = codex_account_fingerprint(path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertIn("codex-fixture-refresh-token-secret", raw_text)
        self.assertNotIn("codex-fixture-refresh-token-secret", fp)
        self.assertNotIn("codex-fixture-access-token", fp)

    def _temp_file(self, content: str):
        import tempfile

        class _Ctx:
            def __enter__(self_inner):
                fd, name = tempfile.mkstemp(suffix=".json")
                with open(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                self_inner.path = Path(name)
                return self_inner.path

            def __exit__(self_inner, *exc_info):
                self_inner.path.unlink(missing_ok=True)

        return _Ctx()


class TestSameAccountDifferentMachineFixtures(unittest.TestCase):
    """验收标准的核心断言：同账户不同机器 -> 同指纹；不同账户 -> 不同指纹。

    用两份独立的 fixture 文件模拟"两台机器各自的本地配置"，而不是共享同一个
    Python 对象——这样才是真的在验证"跨文件/跨机器"这件事，不是验证同一份
    内存对象两次相等。
    """

    def test_two_machines_same_claude_account_produce_same_fingerprint(self) -> None:
        machine_a_config = {"oauthAccount": {"accountUuid": "shared-uuid", "emailAddress": "a@x.com"}}
        machine_b_config = {"oauthAccount": {"accountUuid": "shared-uuid", "emailAddress": "a@x.com"}, "numStartups": 999}
        fp_a = compute_account_fingerprint("claude", read_claude_stable_account_id(machine_a_config))
        fp_b = compute_account_fingerprint("claude", read_claude_stable_account_id(machine_b_config))
        self.assertEqual(fp_a, fp_b)

    def test_two_machines_different_codex_account_produce_different_fingerprint(self) -> None:
        machine_a_auth = {"tokens": {"account_id": "acct-A"}}
        machine_b_auth = {"tokens": {"account_id": "acct-B"}}
        fp_a = compute_account_fingerprint("codex", read_codex_stable_account_id(machine_a_auth))
        fp_b = compute_account_fingerprint("codex", read_codex_stable_account_id(machine_b_auth))
        self.assertNotEqual(fp_a, fp_b)


if __name__ == "__main__":
    unittest.main()
