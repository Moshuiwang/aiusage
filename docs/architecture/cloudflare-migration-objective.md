# 长期目标：完全迁移到 Cloudflare（草案）

> 这是北极星目标文档：定义「到哪算赢、不达标算输」。
> 「怎么走」的路线见 [`cloudflare-worker-native-migration-plan.md`](cloudflare-worker-native-migration-plan.md)，它的 Phase 0-6 是本目标的里程碑。
> 本文为草案，尚未开始执行。

---

## 1. 北极星（终局）

`aiusage.chunbai.com` 背后的中心后端 **100% 由 Cloudflare 承担**（Worker + D1 + 按需 KV/R2/Queues/Cron/Secrets）。

**关停条件（达成此条件才算真正脱离 VPN2）**：
> 把 VPN2 切到 **冷备**（不再回源、不再承载任何线上请求）后，所有用户入口——Dashboard、iPhone、Apple Watch、macOS——连续 **7 天**正常，无人工干预、无降级。满足后 VPN2 保持冷备（不物理下线），作为数据与回退的安全网。

这个「冷备 7 天无事故」是可证明的验收点，把「迁移完了吗」从主观判断变成客观事实。

---

## 2. 已锁定的决策

| 决策 | 选择 | 含义 |
| --- | --- | --- |
| VPN2 最终状态 | **长期冷备**（不物理下线） | 永远留作数据安全网 + 一键回退源；不删原始 SQLite |
| 生产 D1 | **新建独立 production D1** | 现有 `aiusage-dev-db` 退回纯开发用，理清「生产跑在 dev 库」的现状 |
| D1 计费 | **免费档** | 设计必须主动压低读写量（查询时计算 + 缓存、批量写），额度核对是里程碑 1 的硬任务 |
| 历史数据迁移 | **由 Claude 主导** | Claude 出方案、派 codex 执行、做字段级校验；VPN2 冷备保证源数据不丢 |

「新建 vs 扶正」之所以选新建：免费档下要重新规划容量和写入策略，新建一个干净的 production 库比在带生产流量的 dev 库上改更安全，且天然把 dev/prod 分开。

---

## 3. 完成的定义（DoD，逐项可勾）

用户可见、可验证的事实，不靠「代码看起来对了」：

- [ ] 切换前后，今日 / 周 / 月 / all、machine/account 过滤、limits/quota 展示**逐项一致**。
- [ ] 真实设备能把 `/ingest`、`/ingest-limits` 打通，数据写入 D1。
- [ ] **D1 与原 SQLite 口径逐字段对得上**（行数 + 抽样字段双重校验，不是「大概一致」）。
- [ ] iPhone / Watch / macOS 读 `/api/mobile/summary` **不退化**（字段、刷新、stale 语义都在）。
- [ ] Dashboard 登录、静态资源、summary 正常。
- [ ] **本机 macOS 菜单栏 popover 截图核对（切换的最终放行点）**：切到 Cloudflare 后，popover 展示的数据与切换前一致，并能反映刚 push 的最新用量——同一张截图同时证明「上传链路对」和「展示数据对」。
- [ ] VPN2 切冷备后入口仍可用，且**任意里程碑都能一键回退**到上一稳定态。

> 验收方法：菜单栏 popover 读的是 `/api/mobile/summary`，URL 在切换前后不变（切换发生在 Cloudflare 后端，proxy→Native），所以是干净的 A/B。
> 两道校验：①**自动**——codex 对同一请求做切换前后字段级比对（rigorous）；②**人眼**——codex 截 popover 图核对渲染结果（sanity）。触发 popover 显示可能需要你先点开菜单栏图标，codex 再用 `screencapture` 截图。

---

## 4. 非目标 / 边界（必须写死，最容易被误解）

> 「完全迁移到 Cloudflare」指的是**中心后端**。设备本地采集——`ccusage`、`mswusage-codex`、本机 Codex/Claude auth 读取、`codex app-server` / CLI fallback、各平台定时任务——**永远留在设备上**。Cloudflare 没有用户本机的系统账号上下文，替代不了这些。
>
> 本次迁移**不减少设备侧任何东西**，只去掉对 VPN2 这台中心机的依赖。

不做：多租户、团队 SaaS、云端反向采集、把本地估算包装成官方额度。

---

## 5. 里程碑（按门槛驱动，不设假 deadline）

每个里程碑有明确退出条件，达不到不进下一关。对应迁移规划的 Phase。

| 里程碑 | 退出条件（达成才算过） |
| --- | --- |
| M0 盘点 + 合同测试 | 现有 API 的字段/错误码被 fixture 合同测试固化，可机器重放 |
| M1 D1 schema + 免费额度核对 | schema 定稿、SQL 差异逐条核对、免费档读写/存储额度算清并给出写入策略 |
| M2 只读 API（TS Worker，测试数据） | `/api/summary`、`/api/mobile/summary` 输出与 Python 版逐字段一致（合同测试通过） |
| M3 写入 + 双写 | `/ingest`、`/ingest-limits` 写 D1；VPN2 与 D1 双写并存，随时可比可退 |
| M4 数据迁移 + 结果对比 | 历史 SQLite→D1 导入完成且字段级校验通过；两边 API 逐项对齐；**先截一张切换前的 macOS popover 作为基线** |
| M5 切流 | `aiusage.chunbai.com` 后端指向 Native Worker，不再回源 VPN2；回退路径就绪；**切后 popover 截图 + 字段级比对与基线一致（上传、展示都对）才算放行** |
| M6 冷备 | VPN2 转冷备，满足北极星的「7 天无事故」关停条件 |

---

## 6. 数据不丢的保证

- **VPN2 冷备本身就是安全网**：迁移全程不删 VPN2 上的原始 SQLite，最坏情况一键切回。
- **迁移是「导出 + 导入 + 校验」三步，缺一不可**：导入后必须过行数校验 + 抽样字段校验两道关，校验不过不切流。
- **切流前保留双写期**（M3）：同一份上报同时进老库和 D1，确保切流时 D1 已是热数据，不是冷启动。

---

## 7. 执行操作模型（codex 主导，Claude 只计划/监督/review）

这是本目标的工作方式，也适用于后续大部分代码与运维任务。

### 角色

- **Claude（架构/计划/监督/review）**：把目标拆成任务包、写规格与验收、派活给 codex、做最终 review gate、向用户汇报。**不写生产代码、不直接跑生产运维。**
- **codex（执行）**：写代码、写测试、跑本地测试、起草迁移脚本、本地/dev wrangler。默认模型 `gpt-5.5`。
- **运维（codex 指向兄弟目录）**：真实 Cloudflare 账号操作走 `cloud-flare` 目录，凭据在其 `.env`，Claude 不读不输出。

### codex 调用约定

```bash
# 应用侧实现（高风险 / 迁移 / 口径相关）：高思考 + 可写沙箱
codex exec -m gpt-5.5 -c model_reasoning_effort="high" -s workspace-write "<任务包内容>"

# 机械 / 样板 / 文档改动：中思考
codex exec -m gpt-5.5 -c model_reasoning_effort="medium" -s workspace-write "<任务>"

# 只读调研：只读沙箱
codex exec -s read-only "<问题>"

# 代码评审（codex 自带）
codex review                 # 或 codex exec review

# 真实 Cloudflare 账号运维：切到兄弟目录
codex exec -C /Users/wangzhipeng/Documents/cloud-flare -c model_reasoning_effort="high" "<运维任务>"
```

并行需要时，可由 subagent 各驱动一条 codex 流，互不阻塞；编排和最终 review 仍归 Claude。

### 监督 / review 闭环（每个任务）

1. Claude 写任务包（TDD：先写失败测试）。
2. 派给 codex 执行。
3. codex 返回 diff + 测试结果。
4. Claude 做最终 review：正确性、**口径逐字段一致**、边界合规、测试全绿。
5. 通过 → 汇报；**commit 只在用户明确同意后**。
6. 运维步骤同理，Claude 审 smoke 报告，不亲自跑生产。

### codex 必须遵守的护栏

- 遵守 `AGENTS.md`、TDD；没有用户同意不 `git add`/`commit`。
- 不读、不打印 `.env`、token、原始 usage 日志。
- 应用代码只在本仓库；账号运维只在 `cloud-flare` 目录。
- 每次改动保持现有 API 合约；字段级一致是硬门槛。

### 授权与升级边界（2026-06-22 用户授权）

用户授权 Claude 自主推进与决策，无需逐步签字。Claude 在下列安全网下自主执行全部里程碑（含新建 Cloudflare 资源、配置 Secrets 但不读明文、执行数据导入、切流）：

- 可逆性：VPN2 冷备＝回退源；双写期 + 字段级/截图校验前置；任意里程碑可一键回退。
- 默认决策：会话密钥沿用（登录态无感）；生产用新建 free D1；账号操作经 `cloud-flare` 运维 codex。

仅在真正必须人类决策时才升级：①需超出 free tier 的付费；②缺访问权限 / 账号被阻塞 / 运维 codex 无法鉴权；③校验门无法通过且排查不出原因（数据完整性风险）；④任何不可逆删除（设计上应避免）。

---

## 8. 风险与回退

| 风险 | 应对 |
| --- | --- |
| 免费 D1 额度不够 | M1 先算清额度；查询时计算 + 缓存、批量写；超标则回到目标第 2 节重审「免费档」决策 |
| SQLite→D1 SQL 差异 | M1 逐条核对；不对齐的换写法，用合同测试兜底 |
| 切流后发现口径偏差 | 双写期 + 字段级校验前置；任意里程碑可一键回退 VPN2（它是冷备） |
| 登录态 / token 迁移 | 决定是否沿用会话密钥（沿用＝用户无感）；token 进 Secrets，由运维配 |
| 客户端残留旧配置 | 切流前清点 iOS/Watch/macOS 的 base URL、token、缓存；用真机而非缓存验收 |

**回退是一等约束**：每个里程碑都必须保留「退回上一稳定态」的能力，直到 M6 冷备观察期结束。

---

## 9. 进度怎么追踪

- 每个里程碑落成一个或多个任务包（沿用 `TP-V2-xxx`，入口迁移起点是 `TP-V2-083`）。
- `docs/architecture/governance-state.md` 标记当前在哪一轮；`docs/status.md` 反映整体进度。
- 本目标文档保持稳定，少改；变的是路线和任务包，不是北极星。
