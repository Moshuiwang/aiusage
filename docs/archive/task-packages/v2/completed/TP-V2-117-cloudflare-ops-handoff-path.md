# TP-V2-117 Cloudflare Ops Handoff Path

Version: V2
ID: TP-V2-117
Status: done
Type: documentation
Depends on: none
Parallel with: none

## Goal

让 AI Usage 的 Cloudflare 账号侧部署与线上验收始终交接到实际存在的 Ops 工作区。

## Context

实际 Ops 工作区为 `/Users/wangzhipeng/Documents/ops`；旧文档仍引用不存在的旧目录，导致发布交接失败。

## Scope

- 更新 Cloudflare 交接入口、架构说明和相关任务包中的旧目录引用。
- 指明 Ops Agent 必须读取其自身 `AGENTS.md` 并使用受保护凭据环境。

## Out of Scope

- 不读取或记录任何凭据。
- 不改 Worker、Cloudflare 资源、DNS、路由或应用逻辑。

## Red Test

- 修改前，仓库搜索仍能找到不存在的旧 Ops 入口。

## Implementation

1. 把所有运行中的交接说明统一为实际 Ops 目录。
2. 保留账号侧操作与应用代码职责的边界。

## Acceptance Criteria

- 所有 Ops 交接入口都指向 `/Users/wangzhipeng/Documents/ops`。
- 不再出现旧 `cloud-flare` 路径。
- 文档不含凭据值。

## Verification

```bash
legacy_path='/Users/wangzhipeng/Documents/cloud'"-flare"
rg -n "$legacy_path" README.md docs cloudflare
rg -n '/Users/wangzhipeng/Documents/ops' docs cloudflare
```

## Handoff

- 回报已更新的入口文件与 grep 验证结果。
