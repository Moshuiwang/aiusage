# TP-V1-005 Atomic JSON Writer

Version: V1
ID: TP-V1-005
Status: ready
Type: implementation
Depends on: none
Parallel with: TP-V1-006

## Goal

确保 `latest.json` 原子写入，Widget 不会读到半截 JSON。

## Context

展示层只读快照，写入过程必须保护旧快照。

## Scope

- `src/ai_usage_widget/storage_json.py`
- JSON writer tests

## Out of Scope

- 不改 snapshot schema。
- 不改 sync-widget。

## Red Test

- temp dir 写入成功。
- 父目录不存在时创建或结构化失败。
- 写入失败不破坏旧文件。
- 输出 JSON 可解析。

## Implementation

- 临时文件写入。
- fsync 或合理的本地文件安全策略。
- rename 替换。

## Acceptance Criteria

- 失败时旧文件仍可读。
- 成功时没有残留半截 JSON。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报失败保护测试。
