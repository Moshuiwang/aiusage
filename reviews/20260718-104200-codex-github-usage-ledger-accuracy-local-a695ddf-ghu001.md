# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: user
  repo_adapter_present: false
  setup_advisory: skipped
  risk_score: 18
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: deep
  selected_rounds: 2
  quota_class: unknown
  reviewer_preflight:
    subagent_available: true
    cli_exists: skipped
    short_answer_smoke: skipped
    reason: "用户明确要求 subagent review，本地 Codex subagent 可用"
  branch_gate:
    current_branch: codex/github-usage-ledger-accuracy
    default_branch: main
    allowed: true
    reason: "在独立 PR 分支执行只读 review"
  actual_reviewer: codex-subagent
  reviewer_interface: subagent
  actual_model: delegated
  model_resolution:
    kind: quota-aware
    value: delegated
  depth_resolution:
    kind: repo_default
    value: ["deep prompt scope"]
    confidence: delegated
  scope: origin/main...HEAD
  rounds_completed: 2
  reasons:
    - "Diff 涉及 Usage Ledger 准确性、SQLite/D1 写入和历史事实清理"
    - "首轮确认一个 P1，真实修复后执行第二轮复核"
artifact_identity:
  artifact_kind: review_report
  run_id: ghu001
  task_id: TP-V2-072
  branch: codex/github-usage-ledger-accuracy
  base_ref: origin/main
  head_ref: HEAD
  scope: origin/main...HEAD
```

## Reviewer Output

首轮 review 基于 [review request](20260718-usage-ledger-github-request-a695ddf-ghu001.md) 检查完整 diff，发现 SQLite HTTP 重试可能被误判为第二次独立完整扫描。修复后，同一 subagent 对三文件修复 diff 做了第二轮只读复核。

## Triage

```yaml
findings:
  - id: R1
    reviewer_severity: P1
    confirmed_severity: P1
    file: src/ai_usage_widget/server_services.py
    line: 89
    source: introduced
    summary: "同一完整扫描 payload 的 HTTP 重试会被 SQLite 准确性状态机重复计次"
    evidence: "服务端原先每次请求生成新的 collected_at，并将其作为扫描身份；相同 payload 重试会从 matching_full_scans=1 变为 2，与使用 req.observed_at 的 Cloudflare 路径不一致。"
    action: fixed
```

## Fixes

- `write_sqlite` 新增可选的 `accuracy_observed_at`，仅供准确性状态机识别稳定扫描身份。
- HTTP ingest 把 payload 的 `req.observed_at` 传入准确性状态机；来源新鲜度、collection run 和响应 `accepted_at` 继续使用服务器接收时间。
- 新增服务层回归测试，验证同一完整扫描 payload 重试两次仍保持 `unverified / matching_full_scans=1`。
- 第二轮 subagent review 确认原 P1 已解决，未发现新的 P0-P2。

## Verification

- Red test：修复前复现 `verified / matching_full_scans=2`，按预期失败。
- `tests.test_server_services + tests.test_storage_sqlite`：16 项通过。
- Usage Ledger 相关 Python 定向测试：111 项通过。
- Cloudflare Native Worker：27 项通过。
- Python 全量：306 项中 304 项通过；2 项失败是未被本 PR 修改的旧 Cloudflare 路由/文档断言，与当前 D1 生产架构不一致。
- `git diff --check`：通过。
- 敏感信息扫描：未发现 token、私钥、原始 usage 日志或 `config/sources.local.json`。

## Remaining Risk

- 扫描重放身份仍依赖客户端 `observed_at`。当前 pusher 的网络重试复用同一 payload，因此已覆盖实际路径；若未来客户端在每次重试前重新生成 payload，需要引入独立 `scan_id`。
- 全量测试保留 2 个历史 Cloudflare 部署合同失败，未在本 PR 中扩大范围修复。
- 生产部署和真实历史回填不在本次 push/PR 操作内执行。
