# TP-V1-015 App Group Snapshot Path

Version: V1
ID: TP-V1-015
Status: ready
Type: implementation
Depends on: TP-V1-005
Parallel with: TP-V1-014

## Goal

固定 WidgetKit sandbox 下的 snapshot 同步和读取路径。

## Context

Python `sync-widget` 和 Swift `SnapshotLoader` 必须读取同一位置。

## Scope

- `src/ai_usage_widget/widget_sync.py`
- Swift `SnapshotLoader`
- docs/widget-macos.md
- Python and Swift tests

## Out of Scope

- 不做签名发布。
- 不改 Widget UI。

## Red Test

- Python sync temp destination。
- missing input。
- Swift loader default path。
- environment override path。

## Implementation

- 固定路径规则。
- 文档同步。

## Acceptance Criteria

- Python 和 Swift 路径一致。
- 测试不写真实 container。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
cd widget/macos
swift test
```

## Handoff

- 汇报默认路径和 override 方式。
