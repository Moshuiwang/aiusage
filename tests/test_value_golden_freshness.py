"""Issue #63 A 组：``value_golden.json`` 防陈旧守卫。

``cloudflare/native-worker/test/value_golden.json`` 是从 Python 读模型
（``snapshot_builder`` + ``mobile_summary``）导出的快照，唯一消费方是
``cloudflare/native-worker/test/parity.test.ts``——Native Worker 拿它做跨实现 parity。

这种 golden 有一个静默失效模式：Python 侧新增字段后没人重新生成 golden，
于是 golden 停止守护那个字段；而跨实现 parity 因为「两边都没有新字段」继续报绿。
测试全绿，守护范围却在悄悄缩小。

所以生成逻辑的 owner 是**本测试模块**（``GOLDEN_PATH`` + ``_collect_records()``），
``scripts/gen_value_golden.py`` 反过来从这里 import——和
``tests/test_provider_slots_parity.py`` / ``scripts/gen_provider_slots_golden.py`` 同构。
本文件里的守卫每次都重新生成一遍并与已提交的 golden 逐条比对：
一旦读模型的输出变了而 golden 没跟上，这里立刻变红。

变红时的正确动作是**复核 diff 后重新生成**：

    PYTHONPATH=src python3 scripts/gen_value_golden.py

而不是放宽这里的断言。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ai_usage_widget.mobile_summary import build_mobile_summary
from ai_usage_widget.snapshot_builder import build_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
SEED_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "seed.sql"
GOLDEN_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "value_golden.json"

TIMEZONE = "Asia/Shanghai"
FIXED_NOW = "2026-06-03T12:00:00+08:00"

# 易变字段：与运行时刻、临时目录、文件大小绑定，重放时必然不同，比对前统一抹掉。
VOLATILE_FIELDS = {
    "accepted_at",
    "generated_at",
    "mtime",
    "path",
    "size_bytes",
    "updated_at",
}

REQUESTS = [
    ("summary-today", "/api/summary?date=2026-06-03&period=today"),
    ("mobile-summary-today", "/api/mobile/summary?date=2026-06-03&period=today"),
    ("summary-week", "/api/summary?date=2026-06-03&period=week"),
    ("mobile-summary-week", "/api/mobile/summary?date=2026-06-03&period=week"),
    ("summary-month", "/api/summary?date=2026-06-03&period=month"),
    ("mobile-summary-month", "/api/mobile/summary?date=2026-06-03&period=month"),
    ("summary-all", "/api/summary?date=2026-06-03&period=all"),
    ("mobile-summary-all", "/api/mobile/summary?date=2026-06-03&period=all"),
    ("summary-week-machine-filter", "/api/summary?date=2026-06-03&period=week&machine=macbook-pro"),
    ("mobile-summary-week-machine-filter", "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev"),
    ("summary-week-account-filter", "/api/summary?date=2026-06-03&period=week&account=alice"),
    ("mobile-summary-week-account-filter", "/api/mobile/summary?date=2026-06-03&period=week&account=bob"),
    ("summary-week-observed-limits", "/api/summary?date=2026-06-03&period=week"),
    ("mobile-summary-week-observed-limits", "/api/mobile/summary?date=2026-06-03&period=week"),
]

MAX_DIFFS_REPORTED = 40
MAX_VALUE_CHARS = 200


class TestValueGoldenFreshness(unittest.TestCase):
    """golden 必须能自动发现自己陈旧。"""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.regenerated = _collect_records()

    def test_committed_golden_matches_freshly_generated_records(self) -> None:
        """已提交的 golden 必须等于此刻读模型重放出来的结果。"""
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        diffs = _diff_paths(golden, self.regenerated, "records")
        if diffs:
            self.fail(
                f"cloudflare/native-worker/test/value_golden.json 已经陈旧（{len(diffs)} 处差异），"
                "不再等于 Python 读模型当前的输出——它正在停止守护下列字段，"
                "而跨实现 parity 会因为「两边都没有新字段」继续报绿。\n"
                "复核下列差异后重新生成：PYTHONPATH=src python3 scripts/gen_value_golden.py\n"
                + _format_diffs(diffs)
            )

    def test_golden_covers_every_declared_request(self) -> None:
        """请求清单变了而 golden 没跟上，同样算陈旧。"""
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            [record["name"] for record in golden],
            [name for name, _ in REQUESTS],
            "golden 覆盖的请求集合与 REQUESTS 不一致，需要重新生成。",
        )

    def test_regeneration_is_deterministic(self) -> None:
        """守卫本身不许随机红：同一份 fixture 连续重放两次必须完全相同。

        固定时间 + 固定时区 + 抹掉易变字段，这三条只要有一条没做到，
        上面那条防陈旧断言就会变成噪音，很快会被人当成误报关掉。
        """
        diffs = _diff_paths(self.regenerated, _collect_records(), "records")
        if diffs:
            self.fail(
                f"重放结果不确定（{len(diffs)} 处差异），说明还有易变字段没被固定或抹掉：\n"
                + _format_diffs(diffs)
            )


def _collect_records() -> list[dict[str, Any]]:
    """按 ``REQUESTS`` 重放读模型，产出 golden 的全部记录。

    ``scripts/gen_value_golden.py`` 从这里 import，保证「生成」与「校验」共用同一份逻辑。
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "value-parity.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.executescript(SEED_PATH.read_text(encoding="utf-8"))

        return [
            _record(name=name, request_path=request_path, db_path=db_path, temp_dir=Path(temp_dir))
            for name, request_path in REQUESTS
        ]


def _record(*, name: str, request_path: str, db_path: Path, temp_dir: Path) -> dict[str, Any]:
    parsed = urlparse(request_path)
    params = parse_qs(parsed.query)
    payload = _build_payload(parsed.path, params, db_path, temp_dir)
    return {
        "name": name,
        "request": {
            "method": "GET",
            "path": request_path,
            "auth": True,
        },
        "response": {
            "status": 200,
            "content_type": "application/json",
            "location": None,
            "body": mask_volatile(payload),
        },
    }


def _build_payload(
    path: str,
    params: dict[str, list[str]],
    db_path: Path,
    temp_dir: Path,
) -> dict[str, Any]:
    snapshot = _build_snapshot_payload(
        db_path=db_path,
        output_path=temp_dir / "request-snapshot.json",
        date_str=_single(params, "date", "2026-06-03"),
        period=_single(params, "period", "today"),
        machine_filter=_optional_single(params, "machine"),
        account_filter=_optional_single(params, "account"),
    )
    snapshot = _with_machine_source_ids(snapshot)
    if path == "/api/mobile/summary":
        return build_mobile_summary(snapshot)
    return snapshot


def _build_snapshot_payload(
    *,
    db_path: Path,
    output_path: Path,
    date_str: str,
    period: str,
    machine_filter: str | None,
    account_filter: str | None,
) -> dict[str, Any]:
    build_snapshot(
        db_path=str(db_path),
        output_path=str(output_path),
        date_str=date_str,
        timezone_str=TIMEZONE,
        current_time_str=FIXED_NOW,
        period=period,
        machine_filter=machine_filter,
        account_filter=account_filter,
    )
    return json.loads(output_path.read_text(encoding="utf-8"))


def _single(params: dict[str, list[str]], name: str, default: str) -> str:
    values = params.get(name)
    if not values:
        return default
    return values[0]


def _optional_single(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


def _with_machine_source_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    groups = snapshot.get("groups")
    if not isinstance(groups, dict):
        return snapshot
    machines = groups.get("by_machine")
    if not isinstance(machines, list):
        return snapshot
    for machine in machines:
        if not isinstance(machine, dict):
            continue
        source_ids = set(str(source_id) for source_id in machine.get("source_ids") or [])
        users = machine.get("users")
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                source_ids.update(str(source_id) for source_id in user.get("source_ids") or [])
        if source_ids:
            machine["source_ids"] = sorted(source_ids)
    return snapshot


def mask_volatile(value: Any, field_name: str = "") -> Any:
    if field_name in VOLATILE_FIELDS or field_name.endswith("_path"):
        return "<masked>"
    if isinstance(value, list):
        return [mask_volatile(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_volatile(item, key) for key, item in value.items()}
    return value


def _diff_paths(golden: Any, regenerated: Any, path: str) -> list[str]:
    """逐字段比对，返回「差在哪个 record 的哪个字段」的可读清单。"""
    if isinstance(golden, dict) and isinstance(regenerated, dict):
        diffs: list[str] = []
        for key in sorted(set(golden) | set(regenerated)):
            child = f"{path}.{key}"
            if key not in golden:
                diffs.append(f"{child}: golden 缺失该字段，读模型现在会产出 {_brief(regenerated[key])}")
            elif key not in regenerated:
                diffs.append(f"{child}: golden 里多出该字段，读模型已不再产出（golden={_brief(golden[key])}）")
            else:
                diffs.extend(_diff_paths(golden[key], regenerated[key], child))
        return diffs

    if isinstance(golden, list) and isinstance(regenerated, list):
        diffs = []
        if len(golden) != len(regenerated):
            diffs.append(f"{path}: 长度不同，golden={len(golden)} regenerated={len(regenerated)}")
        for index in range(min(len(golden), len(regenerated))):
            label = _element_label(golden[index], index)
            diffs.extend(_diff_paths(golden[index], regenerated[index], f"{path}[{label}]"))
        return diffs

    if golden != regenerated or type(golden) is not type(regenerated):
        return [f"{path}: golden={_brief(golden)} regenerated={_brief(regenerated)}"]
    return []


def _element_label(element: Any, index: int) -> str:
    if isinstance(element, dict):
        for key in ("name", "provider", "machine", "account", "date"):
            value = element.get(key)
            if isinstance(value, str):
                return f"{index}:{value}"
    return str(index)


def _brief(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=repr)
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS] + f"...(共 {len(text)} 字符)"
    return text


def _format_diffs(diffs: list[str]) -> str:
    shown = diffs[:MAX_DIFFS_REPORTED]
    lines = [f"  - {line}" for line in shown]
    if len(diffs) > len(shown):
        lines.append(f"  ...(另有 {len(diffs) - len(shown)} 处差异未列出，共 {len(diffs)} 处)")
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
