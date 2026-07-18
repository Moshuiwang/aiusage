# TP-V2-112 GitHub Actions CI Baseline

Version: V2
ID: TP-V2-112
Status: done
Type: implementation
Depends on: TP-V2-114, TP-V2-115
Parallel with: none

## Goal

为 `Moshuiwang/aiusage` 建立最小权限的 GitHub Actions CI，让后续 Pull Request 自动显示
Python、Cloudflare Worker、macOS Swift 和 iOS Swift 四类核心检查；满足获批 Plan 的条件
合并门禁后由 Executor 合并。

## Context

Loop Plan #31 的待批准新 revision 继续把 GitHub Issue #32 设为首个 Epic。当前仓库没有 GitHub Actions
workflow，也无法为私有仓库启用 branch protection；首个 CI PR 依靠本地全量验证、一轮独立
Review 和 PR 自身 Actions 完成 bootstrap。CI 合并后，Epic #29 与 #30 的 PR 必须自动触发检查。

## Scope

- 新增 `tests/test_github_actions_ci.py`，固定 workflow 的触发、权限、job 和命令合同。
- 新增 `.github/workflows/ci.yml`。
- `pull_request` 和 `main` 的 push 自动触发。
- workflow 顶层只授予 `contents: read`，不引用 secrets，不访问生产 API。
- 分开提供 Python、Worker、macOS Swift、iOS Swift jobs。
- 同一 PR 的旧运行可被新提交取消。
- Python job 运行仓库全量 unittest。
- Worker job 使用锁文件安装依赖并运行 Native Worker 测试。
- macOS Swift job 运行 `clients/macos` 测试。
- iOS Swift job 运行 `mobile/ios` 与 Xcode integration 测试。

## Out of Scope

- 不创建、读取或修改 GitHub Secrets。
- 不访问生产 API、D1、BIAI 或真实额度来源。
- 不部署生产，不安装 Mac/iPhone App。
- 不直接 push `main`，不创建 branch protection，不绕过条件合并门禁。
- 不顺带修复 TP-V2-114、TP-V2-115 之外的既有测试失败；如有失败，记录准确证据并停止。

## Red Test

先新增 `tests/test_github_actions_ci.py` 并运行：

```bash
PYTHONPATH=src python3 -m unittest tests.test_github_actions_ci -v
```

在 `.github/workflows/ci.yml` 尚不存在时，测试必须因目标行为缺失而失败。失败测试至少断言：

- workflow 文件存在；
- 触发 `pull_request` 和 `main` push；
- 顶层权限为只读；
- 四类 job 存在且包含获批验证命令；
- 不出现 secrets、生产域名或 `continue-on-error`。

## Implementation

1. 确认失败测试只因 workflow 缺失而失败。
2. 新增最小 `.github/workflows/ci.yml`。
3. 使用 `actions/checkout`、官方语言运行环境和仓库锁文件安装依赖。
4. 为每类 job 提供稳定、可辨认的名称与超时。
5. 启用 workflow 级并发取消，不弱化任何测试失败。
6. 运行定向合同测试、各 job 对应本地命令和全量验证。

## Acceptance Criteria

- Pull Request 页面能分别看到 Python、Worker、macOS Swift、iOS Swift checks。
- 任一命令失败时对应 job 失败，不使用 `continue-on-error` 掩盖。
- workflow 不需要 secrets，不访问生产业务数据。
- 后续 Epic #29、#30 的 PR 自动触发同一 CI。
- 本地全量验证、一轮独立 Review 和当前 PR Actions 证据指向同一 head SHA。
- PR 保持 Draft，完成证据后转为 Ready；只有最新 head 的验证、Review、CI 全绿且无未解决
  P0/P1 时，才按获批 Plan 的 `authorization.merge_pr` 执行。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_github_actions_ci -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm ci
npm run cf:native:test
swift test --package-path clients/macos
swift test --package-path mobile/ios
python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
```

GitHub 外部验证：

- Draft PR 上四类 jobs 均针对最新 head SHA 运行。
- 所有必需 jobs 成功后才转为 Ready for review。
- merge 后回读 workflow 为 enabled，并确认 `main` 上真实 run 成功。

## Handoff

- 汇报 workflow jobs、触发条件和权限边界。
- 汇报 Red Test 的预期失败及修复后的验证结果。
- 汇报 Review finding、PR head SHA 与 Actions URL。
- 未满足条件合并门禁时不执行 merge。
