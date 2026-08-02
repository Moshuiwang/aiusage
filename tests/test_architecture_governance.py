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


#: 采集端模块。它们跑在用户的 Mac / Linux 机器上，读本机 ccusage / mswusage 与 OS 上下文——
#: 这是 Worker 沙箱结构上做不到的事，所以采集端永远是 Python（#67 决策）。
COLLECTOR_MODULE_GLOBS = (
    "pusher.py",
    "collector_store.py",
    "limits_*.py",
    "mswusage_*.py",
    "deploy_*.py",
)

#: 服务端读模型与 HTTP 编排。按 #67 决策服务端权威已转移到 Worker + D1，
#: 这些 Python 模块已冻结并随 #74 删除。采集端一旦 import 它们，删除就会连带打断采集端——
#: 那正是「Python / TS / 半迁移三种状态并存」最难收拾的形态。
SERVER_SIDE_MODULES = frozenset(
    {"snapshot_builder", "mobile_summary", "server_services", "server"}
)

#: 包名，用于识别 `from ai_usage_widget.snapshot_builder import ...` 这类**绝对导入**。
#: 只认相对导入的守卫会被绝对导入直接绕过——AGENTS.md 点名过这个教训。
PACKAGE_NAME = "ai_usage_widget"


def _server_import_violations(tree: ast.AST) -> list[str]:
    """采集端模块里所有指向服务端读模型的 import。

    四种写法都要认，少认一种就是一条绕过路径::

        import ai_usage_widget.snapshot_builder          # Import, 绝对
        from ai_usage_widget.snapshot_builder import x   # ImportFrom, 绝对
        from .snapshot_builder import x                  # ImportFrom, 相对
        from . import snapshot_builder                   # ImportFrom, 模块名在 names 里
    """
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[-1] in SERVER_SIDE_MODULES and (
                    len(parts) == 1 or parts[0] == PACKAGE_NAME
                ):
                    violations.append("import " + alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            tail = module.split(".")[-1] if module else ""
            if tail in SERVER_SIDE_MODULES:
                violations.append("from " + "." * node.level + module + " import ...")
            elif node.level and not module:
                for alias in node.names:
                    if alias.name in SERVER_SIDE_MODULES:
                        violations.append("from " + "." * node.level + " import " + alias.name)
    return violations


def _collector_module_paths() -> list[Path]:
    src = ROOT / "src" / PACKAGE_NAME
    paths: list[Path] = []
    for pattern in COLLECTOR_MODULE_GLOBS:
        paths.extend(sorted(src.glob(pattern)))
    return paths


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


class TestCollectorDoesNotDependOnServerReadModel(unittest.TestCase):
    """采集端不得依赖服务端读模型（#67 Phase 1c / #72）。

    这条边界的实际含义：**Python 服务端可以被删掉，而采集端一行不受影响。**

    #67 决策服务端收敛为 Worker + D1 单实现，`snapshot_builder` / `mobile_summary` /
    `server_services` / `server` 已冻结并随 #74 删除。而采集端要跑在用户的 Mac / Linux 上
    读本机 ccusage、mswusage 与 OS 用户上下文——Worker 沙箱结构上做不到，所以它永远是
    Python。两者之间只应有 HTTP payload 这一条边。

    一旦采集端 import 了服务端模块，#74 的删除就会连带打断采集端，而那时人会倾向于
    「先把服务端留着」——于是三种状态长期并存，正是决策要消灭的东西。
    """

    def test_no_collector_module_imports_the_server_read_model(self) -> None:
        offenders = {}
        for path in _collector_module_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            violations = _server_import_violations(tree)
            if violations:
                offenders[path.name] = violations
        self.assertEqual(
            offenders,
            {},
            "采集端模块 import 了服务端读模型；服务端删除时会连带打断采集端",
        )

    def test_the_collector_module_list_is_not_empty(self) -> None:
        """防呆：glob 写错时上面那条会因为「一个文件都没扫到」而永远绿。"""
        names = [p.name for p in _collector_module_paths()]
        self.assertIn("pusher.py", names)
        self.assertIn("collector_store.py", names)
        self.assertGreaterEqual(len(names), 6, "采集端模块扫描结果异常: " + str(names))

    def test_the_import_check_catches_both_absolute_and_relative_forms(self) -> None:
        """守卫必须挡住**全部四种**导入写法，少认一种就是一条绕过路径。

        AGENTS.md 点名过这个教训：治理断言只变异了相对导入，绝对导入直接穿过去。
        所以这里逐条往真实源码里注入再检查，而不是只证明「现在是绿的」。
        """
        base = (ROOT / "src" / PACKAGE_NAME / "pusher.py").read_text(encoding="utf-8")
        mutations = (
            ("绝对 import", "import ai_usage_widget.snapshot_builder"),
            ("绝对 from-import", "from ai_usage_widget.snapshot_builder import build_snapshot"),
            ("相对 from-import", "from .snapshot_builder import build_snapshot"),
            ("相对 from 包 import 模块", "from . import snapshot_builder"),
            ("绝对 import mobile_summary", "import ai_usage_widget.mobile_summary"),
            ("相对 import server_services", "from .server_services import build_health_response"),
        )
        for label, injected in mutations:
            with self.subTest(mutation=label):
                mutated = ast.parse(base + "\n\n" + injected + "\n")
                self.assertNotEqual(
                    _server_import_violations(mutated),
                    [],
                    "检查没能抓到「" + label + "」，守卫存在绕过路径",
                )

    def test_the_import_check_does_not_flag_legitimate_imports(self) -> None:
        """反向：合法导入不许误报，否则噪音会让人把守卫关掉。"""
        benign = (
            "import json\n"
            "from .config import DeviceConfig\n"
            "from . import models\n"
            "from ai_usage_widget.version_contract import local_collector_release\n"
            "import ai_usage_widget.timeutil\n"
        )
        self.assertEqual(_server_import_violations(ast.parse(benign)), [])


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
