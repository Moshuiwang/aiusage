"""版本与升级架构决策文档的合同测试（Issue #58 阶段一）。

文档验收必须可执行，而不是靠人眼或一条 `rg`。本测试把文档结构解析出来，
和 `version_contract.py` 的真实常量与真实判定行为逐项比对：

- 字段清单：文档表格里的字段集合必须与代码常量**完全相等**（多一个、少一个都红）
- owner 指认：每个字段必须指到仓库里真实存在的路径
- 四态：文档写的判定条件必须包含代码实际产出的 reason，且用 evaluate 反向验证
- 最低支持版本语义：必须写明是提示还是拒绝，并带上真实 error_type
- 链接：文档内部相对链接必须可解析，且必须被架构总文档引用
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Dict, List

from ai_usage_widget import version_contract


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "architecture" / "version-and-upgrade-contract.md"
ARCHITECTURE_DOC = ROOT / "docs" / "architecture" / "architecture.md"

FIELD_SECTION_COLLECTOR = "### 采集端版本字段"
FIELD_SECTION_SERVER = "### 服务端版本字段"
FIELD_SECTION_PRESENTATION = "### 呈现端版本字段"
STATE_SECTION = "## 四态判定规则"
MIN_SUPPORTED_SECTION = "## 服务端最低支持采集端版本的语义"
MANIFEST_SECTION = "## release manifest 的校验方式"

#: 每个状态对应的 reason。测试会用 evaluate_collector_release 反向验证这张表本身是真的。
STATE_REASONS = {
    "current": ["collector_version_current"],
    "update_available": ["collector_version_behind_target"],
    "unsupported": [
        "collector_version_below_minimum",
        "config_schema_version_below_minimum",
        "parser_schema_version_below_minimum",
    ],
    "rollback_available": ["last_upgrade_failed", "collector_version_ahead_of_target"],
    "unknown": ["collector_release_missing", "collector_version_missing"],
}

REASON_PROBES = {
    "collector_version_current": {"collector_version": "0.4.0"},
    "collector_version_behind_target": {"collector_version": "0.3.0"},
    "collector_version_below_minimum": {"collector_version": "0.1.0"},
    "config_schema_version_below_minimum": {"collector_version": "0.4.0", "config_schema_version": 0},
    "parser_schema_version_below_minimum": {"collector_version": "0.4.0", "parser_schema_version": 1},
    "last_upgrade_failed": {
        "collector_version": "0.4.0",
        "last_upgrade": {"status": "failed", "from_version": "0.3.0"},
    },
    "collector_version_ahead_of_target": {"collector_version": "0.9.0"},
    "collector_release_missing": None,
    "collector_version_missing": {"config_schema_version": 1},
}

PROBE_POLICY = version_contract.VersionPolicy(
    min_supported_collector_version="0.2.0",
    target_collector_version="0.4.0",
    min_supported_config_schema_version=1,
    min_supported_parser_schema_version=2,
)


def _read_doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = None
    for index, line in enumerate(lines):
        if line.strip().casefold() == heading.casefold():
            start = index + 1
            break
    if start is None:
        raise AssertionError(f"文档缺少章节: {heading}")
    collected: List[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            current_level = len(stripped) - len(stripped.lstrip("#"))
            if current_level <= level:
                break
        collected.append(line)
    return "\n".join(collected)


def _table_rows(section_text: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue
        rows.append(cells)
    return rows


def _field_table(section_text: str) -> Dict[str, List[str]]:
    rows = _table_rows(section_text)
    if not rows:
        raise AssertionError("章节里没有表格")
    header = [cell.casefold() for cell in rows[0]]
    if "字段" not in header or "owner" not in header:
        raise AssertionError(f"表头必须包含「字段」和「Owner」列，实际: {rows[0]}")
    return {row[header.index("字段")].strip("`"): row for row in rows[1:]}


class TestVersionContractDocFieldInventory(unittest.TestCase):
    def test_doc_exists_and_is_linked_from_architecture_overview(self) -> None:
        self.assertTrue(DOC.exists(), f"缺少版本与升级架构决策文档: {DOC}")
        self.assertIn("version-and-upgrade-contract.md", ARCHITECTURE_DOC.read_text(encoding="utf-8"))

    def test_collector_field_inventory_matches_code_constants_exactly(self) -> None:
        table = _field_table(_section(_read_doc(), FIELD_SECTION_COLLECTOR))

        self.assertEqual(set(table), set(version_contract.COLLECTOR_VERSION_FIELDS))

    def test_server_field_inventory_matches_code_constants_exactly(self) -> None:
        table = _field_table(_section(_read_doc(), FIELD_SECTION_SERVER))

        self.assertEqual(set(table), set(version_contract.SERVER_VERSION_FIELDS))

    def test_presentation_field_inventory_matches_code_constants_exactly(self) -> None:
        table = _field_table(_section(_read_doc(), FIELD_SECTION_PRESENTATION))

        self.assertEqual(set(table), set(version_contract.PRESENTATION_VERSION_FIELDS))

    def test_every_version_field_points_at_an_owner_path_that_really_exists(self) -> None:
        text = _read_doc()
        for heading in (FIELD_SECTION_COLLECTOR, FIELD_SECTION_SERVER, FIELD_SECTION_PRESENTATION):
            table = _field_table(_section(text, heading))
            header = [cell.casefold() for cell in _table_rows(_section(text, heading))[0]]
            owner_index = header.index("owner")
            for field, row in table.items():
                with self.subTest(section=heading, field=field):
                    owner = row[owner_index].strip("`").strip()
                    self.assertTrue(owner, f"{field} 没有指认 owner")
                    self.assertTrue(
                        (ROOT / owner).exists(),
                        f"{field} 的 owner 路径在仓库里不存在: {owner}",
                    )

    def test_collector_fields_declare_their_wire_path_under_collector_release(self) -> None:
        section_text = _section(_read_doc(), FIELD_SECTION_COLLECTOR)
        header = [cell.casefold() for cell in _table_rows(section_text)[0]]
        self.assertIn("上报路径", header)
        wire_index = header.index("上报路径")
        for field, row in _field_table(section_text).items():
            with self.subTest(field=field):
                wire_path = row[wire_index].strip("`")
                self.assertTrue(
                    wire_path.startswith(f"{version_contract.COLLECTOR_RELEASE_FIELD}."),
                    f"{field} 的上报路径必须挂在 {version_contract.COLLECTOR_RELEASE_FIELD} 下，实际: {wire_path}",
                )


class TestVersionContractDocStateRules(unittest.TestCase):
    def test_state_reason_map_used_by_this_test_is_backed_by_real_behaviour(self) -> None:
        for reason, probe in REASON_PROBES.items():
            with self.subTest(reason=reason):
                release = version_contract.normalize_collector_release(probe)
                result = version_contract.evaluate_collector_release(release, policy=PROBE_POLICY)
                self.assertEqual(result["reason"], reason)
                expected_states = [state for state, reasons in STATE_REASONS.items() if reason in reasons]
                self.assertEqual([result["state"]], expected_states)

    def test_doc_documents_every_state_including_the_unknown_degradation(self) -> None:
        rows = _table_rows(_section(_read_doc(), STATE_SECTION))
        header = [cell.casefold() for cell in rows[0]]
        self.assertIn("状态", header)
        self.assertIn("判定条件", header)
        documented = {row[header.index("状态")].strip("`") for row in rows[1:]}

        self.assertEqual(documented, set(version_contract.ALL_VERSION_STATES))

    def test_each_documented_state_lists_the_reasons_the_code_actually_emits(self) -> None:
        rows = _table_rows(_section(_read_doc(), STATE_SECTION))
        header = [cell.casefold() for cell in rows[0]]
        state_index = header.index("状态")
        condition_index = header.index("判定条件")
        by_state = {row[state_index].strip("`"): row[condition_index] for row in rows[1:]}

        for state, reasons in STATE_REASONS.items():
            for reason in reasons:
                with self.subTest(state=state, reason=reason):
                    self.assertIn(reason, by_state[state])

    def test_doc_records_the_deterministic_severity_order(self) -> None:
        rows = _table_rows(_section(_read_doc(), STATE_SECTION))
        header = [cell.casefold() for cell in rows[0]]
        self.assertIn("排序权重", header)
        state_index = header.index("状态")
        severity_index = header.index("排序权重")
        for row in rows[1:]:
            state = row[state_index].strip("`")
            with self.subTest(state=state):
                self.assertEqual(
                    int(row[severity_index]),
                    version_contract.VERSION_STATE_SEVERITY[state],
                )


class TestVersionContractDocPolicySemantics(unittest.TestCase):
    def test_min_supported_version_section_says_whether_it_prompts_or_rejects(self) -> None:
        section_text = _section(_read_doc(), MIN_SUPPORTED_SECTION)

        self.assertIn("提示", section_text)
        self.assertIn("拒绝", section_text)
        self.assertIn(version_contract.UNSUPPORTED_ERROR_TYPE, section_text)
        self.assertIn("400", section_text)
        self.assertIn("不得无提示丢弃", section_text)

    def test_manifest_section_states_how_a_release_is_verified(self) -> None:
        section_text = _section(_read_doc(), MANIFEST_SECTION).casefold()

        for required in ["sha256", "签名", "校验和", "预检", "原子切换", "回滚"]:
            with self.subTest(required=required):
                self.assertIn(required.casefold(), section_text)

    def test_doc_points_at_code_as_the_source_of_truth_for_thresholds(self) -> None:
        text = _read_doc()

        self.assertIn("version_contract.py", text)
        self.assertIn("MIN_SUPPORTED_COLLECTOR_VERSION", text)
        self.assertIn("TARGET_COLLECTOR_VERSION", text)


class TestVersionContractDocHygiene(unittest.TestCase):
    def test_all_relative_links_resolve(self) -> None:
        text = _read_doc()
        links = re.findall(r"\]\(([^)]+)\)", text)
        checked = 0
        for link in links:
            target = link.split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            with self.subTest(link=link):
                self.assertTrue((DOC.parent / target).resolve().exists(), f"断链: {link}")
        self.assertGreater(checked, 0, "文档里没有任何内部链接，权威入口没写")

    def test_doc_carries_no_credential_or_absolute_home_path(self) -> None:
        text = _read_doc()

        for forbidden in ["/Users/", "/home/", "sk-ant-", "Bearer ", "BEGIN OPENSSH"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
