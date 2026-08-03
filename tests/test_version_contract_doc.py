"""版本与升级架构决策文档的合同测试——**采集端半边 + 全文卫生**。

文档验收必须可执行，而不是靠人眼或一条 `rg`。本测试把文档结构解析出来，
和 `version_contract.py` 采集端保留部分的真实常量逐项比对：

- 采集端字段清单：文档表格里的字段集合必须与代码常量**完全相等**（多一个、少一个都红）
- 采集端 owner 指认与上报路径：每个字段必须指到仓库里真实存在的路径
- release manifest：owner 是 `deploy_release.py`（采集端发布流程），校验方式必须写全
- 链接与凭据扫描：文档内部相对链接必须可解析，且必须被架构总文档引用

**服务端半边**（服务端/呈现端字段表、四态词表与判定、排序权重、最低支持版本语义、
阈值常量指认）已随 #74/PM-6 迁到
`cloudflare/native-worker/test/version-contract-doc.test.ts`，owner 是
`version-contract.ts`；两边不重复实现。
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
MANIFEST_SECTION = "## release manifest 的校验方式"


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

    def test_every_collector_field_points_at_an_owner_path_that_really_exists(self) -> None:
        # 服务端/呈现端表的 owner 路径守卫在 version-contract-doc.test.ts（含
        # 「owner 代码里真的出现相关符号」的更强断言），这里只守采集端半边。
        text = _read_doc()
        table = _field_table(_section(text, FIELD_SECTION_COLLECTOR))
        header = [cell.casefold() for cell in _table_rows(_section(text, FIELD_SECTION_COLLECTOR))[0]]
        owner_index = header.index("owner")
        self.assertEqual(len(table), len(version_contract.COLLECTOR_VERSION_FIELDS))
        for field, row in table.items():
            with self.subTest(field=field):
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


class TestVersionContractDocPolicySemantics(unittest.TestCase):
    def test_manifest_section_states_how_a_release_is_verified(self) -> None:
        section_text = _section(_read_doc(), MANIFEST_SECTION).casefold()

        for required in ["sha256", "签名", "校验和", "预检", "原子切换", "回滚"]:
            with self.subTest(required=required):
                self.assertIn(required.casefold(), section_text)


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
