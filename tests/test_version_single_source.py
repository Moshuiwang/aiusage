"""#124 版本单源治理：pyproject 不得手写第二处版本。

CI 用 `PYTHONPATH=src` 直跑 unittest、不安装包，所以这里不读包元数据，
而是断言 pyproject 的**结构**：版本必须声明为 dynamic，attr 指向
`version_contract.COLLECTOR_VERSION`，且该 attr 真的可解析——
结构上不给「再手写一份版本号」留位置。attr 路径打错时第二条测试会红，
这正是 setuptools 构建期才会炸的那类错误，提前到测试期。
"""

from __future__ import annotations

import importlib
import tomllib
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ATTR = "ai_usage_widget.version_contract.COLLECTOR_VERSION"


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _declared_attr(data: dict) -> Any:
    return (
        data.get("tool", {})
        .get("setuptools", {})
        .get("dynamic", {})
        .get("version", {})
        .get("attr")
    )


class VersionSingleSourceTests(unittest.TestCase):
    def test_pyproject_declares_dynamic_version_from_version_contract(self) -> None:
        data = _pyproject()
        project = data["project"]

        self.assertNotIn(
            "version", project,
            "pyproject 手写了第二处版本号，单源被破坏（版本只能来自 COLLECTOR_VERSION）",
        )
        self.assertIn(
            "version", project.get("dynamic", []),
            "pyproject 必须把 version 声明为 dynamic",
        )
        self.assertEqual(
            _declared_attr(data), EXPECTED_ATTR,
            "dynamic 版本的 attr 必须指向采集端版本合同的 COLLECTOR_VERSION",
        )

    def test_package_dunder_version_matches_collector_version(self) -> None:
        import ai_usage_widget
        from ai_usage_widget.version_contract import COLLECTOR_VERSION

        self.assertEqual(
            ai_usage_widget.__version__, COLLECTOR_VERSION,
            "__init__.__version__ 与 COLLECTOR_VERSION 漂移——版本只能有一个事实源",
        )

    def test_declared_attr_resolves_to_a_semver_string(self) -> None:
        # 从 pyproject 实际声明的 attr 解析（不是从本测试的常量），attr 路径打错时这里红。
        attr = _declared_attr(_pyproject())
        self.assertTrue(attr, "pyproject 未声明 dynamic 版本 attr")

        module_path, _, attribute = str(attr).rpartition(".")
        value = getattr(importlib.import_module(module_path), attribute)

        self.assertRegex(str(value), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
