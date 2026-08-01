from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

VERIFY_CLOUD_PATH = ROOT / "src" / "ai_usage_widget" / "verify_cloud.py"

#: 写方法与写接口路径。verify-cloud 是只读核对入口，源码里出现任何一个都说明边界破了。
WRITE_METHOD_NAMES = ("POST", "PUT", "PATCH", "DELETE")
WRITE_ENDPOINT_PATHS = ("/ingest",)

#: 允许 verify-cloud 引用的包内模块。只放叶子常量模块，
#: 读模型口径必须从成品 DTO 消费，不能反手 import 聚合内部再算一遍。
VERIFY_CLOUD_ALLOWED_PACKAGE_IMPORTS = frozenset({"http_identity"})

#: 直接从存储层取数就绕过了读模型，等于造第三套数字。
VERIFY_CLOUD_FORBIDDEN_MODULES = frozenset({"sqlite3"})

#: 重算口径的原语。verify-cloud 只做「读出来、判定、打印」，不做任何求和与换算。
RECOMPUTE_CALL_NAMES = frozenset({"sum", "fsum", "round", "mean"})
RECOMPUTE_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)

HTTP_CALL_NAMES = frozenset({"Request", "urlopen", "urlretrieve"})


def _write_literal_violations(source: str) -> list[str]:
    violations = []
    for name in WRITE_METHOD_NAMES:
        if re.search(rf"\b{name}\b", source):
            violations.append(f"出现写方法字面量: {name}")
    for path in WRITE_ENDPOINT_PATHS:
        if path in source:
            violations.append(f"出现写接口路径: {path}")
    return violations


def _import_violations(tree: ast.AST) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in VERIFY_CLOUD_FORBIDDEN_MODULES:
                    violations.append(f"禁止导入: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module not in VERIFY_CLOUD_ALLOWED_PACKAGE_IMPORTS:
                violations.append(f"禁止从包内模块导入: {node.module}")
            if not node.level and node.module:
                root = node.module.split(".")[0]
                if root in VERIFY_CLOUD_FORBIDDEN_MODULES:
                    violations.append(f"禁止导入: {node.module}")
    return violations


def _recompute_violations(tree: ast.AST) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in RECOMPUTE_CALL_NAMES:
                violations.append(f"出现重算原语调用: {node.func.id}()")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, RECOMPUTE_OPERATORS):
            violations.append(f"出现算术运算: {type(node.op).__name__}")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, RECOMPUTE_OPERATORS):
            violations.append(f"出现累加赋值: {type(node.op).__name__}")
    return violations


def _http_call_violations(tree: ast.AST) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else ""
        )
        if name not in HTTP_CALL_NAMES:
            continue
        for keyword in node.keywords:
            if keyword.arg == "data":
                violations.append(f"{name}() 带了请求体，只读入口不得携带 data")
            if keyword.arg == "method":
                literal = keyword.value
                if not isinstance(literal, ast.Constant) or literal.value != "GET":
                    violations.append(f"{name}() 的 method 不是常量 GET")
        if name == "Request" and len(node.args) > 1:
            violations.append("Request() 的第二个位置参数就是请求体，只读入口不得使用")
    return violations


class TestVerifyCloudReadOnlyBoundary(unittest.TestCase):
    """把 Issue #60 写在文字里的硬边界变成可执行检查。

    verify-cloud 是唯一一个「读生产数据并给出结论」的 CLI 入口。它有两条最容易被
    悄悄破掉的边界：

    1. **只读**：一旦引入写方法或写接口，核对工具本身就会改动被核对的对象。
    2. **不重算口径**：一旦在 CLI 侧求和或换算，产品就会多出第三套数字，
       而且是最难被发现的那种——它长得像核对结果。

    这两条只写在 Issue 和文档里没有约束力，所以在这里固化成断言。
    """

    def setUp(self) -> None:
        self.source = VERIFY_CLOUD_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_verify_cloud_never_names_a_write_method_or_write_endpoint(self) -> None:
        self.assertEqual(_write_literal_violations(self.source), [])

    def test_verify_cloud_only_issues_read_only_requests(self) -> None:
        self.assertEqual(_http_call_violations(self.tree), [])

    def test_verify_cloud_consumes_finished_dtos_instead_of_aggregation_internals(self) -> None:
        self.assertEqual(_import_violations(self.tree), [])

    def test_verify_cloud_recomputes_no_totals_or_percentages(self) -> None:
        self.assertEqual(_recompute_violations(self.tree), [])

    def test_every_boundary_check_really_catches_its_violation(self) -> None:
        """守卫本身必须能抓到违规，否则它只是让人安心的装饰。

        逐条对真实源码做变异，确认对应的检查会报出问题。任何一条检查退化成
        永远返回空，这个用例就会红。
        """
        mutations = (
            (
                "写方法字面量",
                'HTTP_METHOD = "PO" "ST"\n'.replace('"PO" "ST"', '"POST"'),
                lambda source, tree: _write_literal_violations(source),
            ),
            (
                "写接口路径",
                'INGEST_PATH = "/ingest"\n',
                lambda source, tree: _write_literal_violations(source),
            ),
            (
                "导入聚合内部",
                "from .snapshot_builder import build_snapshot\n",
                lambda source, tree: _import_violations(tree),
            ),
            (
                "直接读存储层",
                "import sqlite3\n",
                lambda source, tree: _import_violations(tree),
            ),
            (
                "自己求和",
                'def _total(rows):\n    return sum(row["total_tokens"] for row in rows)\n',
                lambda source, tree: _recompute_violations(tree),
            ),
            (
                "自己算百分比",
                "def _percent(used, total):\n    return used / total\n",
                lambda source, tree: _recompute_violations(tree),
            ),
            (
                "累加 token",
                "def _accumulate(state, row):\n    state['total'] += row['total_tokens']\n",
                lambda source, tree: _recompute_violations(tree),
            ),
            (
                "带请求体的写请求",
                "def _send(url, body):\n    return urlrequest.Request(url, data=body)\n",
                lambda source, tree: _http_call_violations(tree),
            ),
        )
        for label, injected, check in mutations:
            with self.subTest(mutation=label):
                mutated_source = f"{self.source}\n\n{injected}"
                mutated_tree = ast.parse(mutated_source)
                self.assertNotEqual(
                    check(mutated_source, mutated_tree),
                    [],
                    f"检查没能抓到「{label}」这类违规，守卫已经失效",
                )


class TestArchitectureGovernance(unittest.TestCase):
    def test_architecture_doc_records_current_owners_and_legacy_boundary(self) -> None:
        text = (ROOT / "docs" / "architecture" / "architecture.md").read_text(encoding="utf-8")
        normalized = text.casefold()

        for required in [
            "DevicePusher",
            "server_services.py",
            "snapshot_builder.py",
            "mobile_summary.py",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        for required in ["push ingest", "ssh pull", "legacy"]:
            with self.subTest(required=required):
                self.assertIn(required, normalized)

    def test_gitignore_keeps_local_runtime_artifacts_out_of_commits(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for required in [
            "/data/latest.json",
            "/data/usage.sqlite",
            "/tmp/",
            "/logs/",
            "/.build/",
            "mobile/ios/.build/",
            "mobile/ios-xcode/**/xcuserdata/",
            ".env",
            ".env.local",
            ".env.*.local",
            "*.token",
            "*.secret",
            "*.local.log",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        forbidden_exact_rules = {
            "auth*",
            ".env.*",
            "*.sqlite",
            "*.log",
            "latest.json",
            "*.xcuserstate",
        }
        ignored_lines = set(text.splitlines())
        for forbidden in forbidden_exact_rules:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, ignored_lines)

    def test_widget_configuration_sharing_design_keeps_token_boundary(self) -> None:
        text = (
            ROOT / "docs" / "architecture" / "widget-configuration-sharing.md"
        ).read_text(encoding="utf-8")
        normalized = text.casefold()

        for required in [
            "App Group",
            "Keychain access group",
            "WidgetKit",
            "MobileTokenStore",
            "AIUsageAPIBaseURL",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        for required in [
            "shared userdefaults",
            "token",
            "read-only",
            "reload timeline",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, normalized)
