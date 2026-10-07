---
name: verify
description: ai-usage 的验证入口与证据等级判定。在声称任务完成、汇报测试结果、或需要说明「验证到了哪一级」时使用。
---

# 验证与证据

```bash
scripts/verify.sh                # 按改动面裁剪（不动 cloudflare/ 就不跑 Worker）
scripts/verify.sh --full         # 强制全量：Python + Worker
scripts/verify.sh --python-only  # 只跑 Python
npx --prefix cloudflare/native-worker vitest run --config cloudflare/native-worker/vitest.config.ts <test 文件>
```

- 本地 targeted 测试绿 = 等级 3；全量由 PR CI 承担（等级 4），合并只走 `scripts/merge_pr.sh`。
- 先红后绿与变异证据（破坏 → 变红 → 还原）只能在本地做，CI 替代不了；变异用文件备份还原，
  不用 `git checkout --`。
- 等级 5–7（部署、真机、回源）需要对应环境与授权，未做到就在汇报里列为缺口。
- `verify.sh` 覆盖不到：Swift 测试与构建、真实 Cloudflare 部署与 smoke、真机、真实 ingest 与 ccusage 采集。
