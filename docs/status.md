# Status

> **进度不在本文件。** 当前待办、进行中和已完成状态的唯一真值是 GitHub：
> [Issues](https://github.com/Moshuiwang/aiusage/issues) 与
> [Project #1 AI Usage Delivery](https://github.com/users/Moshuiwang/projects/1)。
> 本文件只记录**不随单个任务变化的当前事实和有效决策**，不写「下一步」，不写已完成清单。

## 当前生产事实

- 生产入口：`https://aiusage.chunbai.com`，由 Cloudflare Worker + Cloudflare D1 承载。
- 正式联合发布：App `2.2.0` / collector `0.4.2`，源码 `40e588c32e25f7b62252e06aff6fab2055174fad`；
  [签名产物](https://github.com/Moshuiwang/aiusage/releases/tag/v2.2.0)包含 macOS arm64 App 和 Linux 源码包。
  Worker 已部署同一源码；各设备是否已实际升级以服务端最后接收版本和对应 Issue 回执为准。
- 生产 Worker：`aiusage-api`，Route 为 `aiusage.chunbai.com/*`；workers.dev 直连已关闭，Pages 项目已删除。
- 生产备份：R2 bucket `aiusage-backups`；Worker 配置了每日维护和月度备份 Cron（UTC 每月 1 日 18:23，即上海时间每月 2 日 02:23）。
- 数据库类型：Cloudflare D1，SQLite-compatible serverless SQL，不是 PostgreSQL。
- VPN2 旧 AI Usage 后端已下线，不再参与读写链路。
- Mac mini 的本机上报：正式菜单栏 App 独立内置采集器，每 1800 秒批量运行用量和额度任务，
  App 退出即停止；已接管本用户旧 LaunchAgent。其他设备的既有调度按其部署回执核对，
  不把本机一体化升级等同于所有机器完成迁移。
- 上报内容：只上传去敏后的 Codex / Claude 小时用量事实和必要归因字段；不上传原始 session、
  prompt、response、tool output 或原始日志路径。
- 去重口径：服务端对同一来源、agent、账号归因、小时窗口和 provenance upsert；
  重复上报更新同一小时桶，不累加成重复用量。
- **服务端只有一份权威实现**：Cloudflare Worker + D1。Python 服务端路径（`server.py` 到
  `mobile_summary.py` 整条链 + 本地 canonical store）**已于 #74 删除**（2026-08-03，删除前
  tag `pre-server-deletion-eee4f35`）。本地开发跑 `scripts/dev_worker.sh`（wrangler dev +
  本地 D1，与生产同款实现）。随 #74 落地的还有：静态资源搬到
  `cloudflare/native-worker/static/`（PM-1）、`collect-limits` 停止写本地 SQLite（PM-2，
  云端 D1 是唯一正本）。生产 Worker 不再配置 Supabase 旁路密钥；历史同步模块不属于生产用户链路。
- **版本可见性已上线**：`/api/summary` 的 `source_status[].version` 与顶层 `version_health`、
  `/api/health` 的 `versions` 返回各设备版本状态。语义是「**最后一次被服务端成功接收的版本**」，
  不是「设备当前运行的版本」——不兼容 payload 在写库之前就被拒绝。
- **生产 D1 迁移已到 `0015`**。`0001_initial_schema.sql` 是**累计快照**：0002/0003/0004/0006 的成果、
  0005 的两个审计索引（#75 已回填）、以及 0008 的 `usage_blocks` 删表（#74，0001 已同步不再建表）
  都收敛在里面，「只跑 0001 的新建库」与迁移链落到同一套表、列与索引；0009 增加拒收上报审计表，
  0010 增加 fact 修订记录，0011 增加对账/投影恢复，0012 增加额度窗口历史，0013 增加
  `account_observations`（账户指纹冲突检测）与 `quota_calibration`（模型周额度校准系数），
  0014 给 rollup 表补 `total_cost` 并新增按时间范围过滤的表达式索引（#190，见下）；
  0015 增加设备申请、独立设备凭据及注册预算表。守卫在
  `tests/test_d1_schema_migration.py`：显式列布局快照（#74 起不再镜像 Python 存储层）、
  两条建库路径 schema 比对、owner 迁移索引重放。**生产 D1 的 0008–0015 已执行并回读确认；2.2.0 未引入新迁移**。
- **模型周额度校准已上线**（epic #180，Worker 侧 #183 已合并）：`account_fingerprint.py`
  采集端上报不可逆账户指纹（#181，写入 `account_observations`，用于发现账户切换/冲突）；
  `cloudflare/native-worker/src/quota-calibration-cron.ts` 每日 cron 按 provider 轮换（3 天一轮，
  规避 Cloudflare Free 单次调用 CPU 预算）用最近 28 天官方周额度读数拟合系数，写
  `quota_calibration`；菜单栏据此显示「≈x.x%」+精度档（PR #194，#184 已合并）。
  **公式 v2（#271，2026-10-07 已部署生产 Worker `77fe284f`；2026-10-12 回源确认三家均为 v2，进入观察期；截止与收口标准以 #271 当前记录为准）**：生产定级 Claude 四族 B（总偏差 10.0%）、Codex sol A / astra·luna·terra B / review none（5.1%）、Antigravity flash B / pro·claude-on-antigravity none（11.0%），系数比与价比一致。口径：有公开价目的族共用一个系数（单一隐藏额度 × API 价比：Claude 按 API
  input 价，Codex 按官方 credit 表），Codex 训练集从已知计量变更日（09-22 / 09-29 / 10-29）截断，
  定级改看逐日留出多天总偏差（A ≤10%、B ≤20%，至少 3 个计分日），有价比的族自身样本不足时最多 B；
  `quota_calibration.backtest_max_err` 列名沿用 v1、含义改为总偏差，`backtest_max_error` 不再下发。
  **App 2.2.0 文案**：A/B 档说明为多天总偏差 ≤10% / ≤20%；Claude 与 Antigravity
  说明按价比估算，Codex 说明按官方额度权重估算。客户端不再解码已废弃的 `backtest_max_error`。**未验证项**：真机长期对照官方额度的持续准确性未知（见 #180、#271）。
- **D1 读取预算优化已部署**（#190，PR #196）：历史预取已改为低频，rollup 补 `total_cost`
  并用时间范围索引减少扫描；`scripts/check_cf_usage.py` 包含 D1 读写水位。当前水位是滚动
  24 小时观测，按脚本和 Issue 回源回执核对，不拿历史 82.5% 或某次发布瞬时结果代替当前值。
- **官方额度失败展示（#281）**：当前失败仍为 missing、当前可用窗口为空；同来源的历史官方
  成功窗口仅在 120 分钟内且尚未重置时，单独通过 `last_successful_windows` 作为“最近成功值”
  下发。App 使用灰色虚线和明确失败提示，历史数字不标为当前可用额度，也不沿用重置倒计时。
  无历史、陈旧、已重置、未来时间、估算或未知记录均不生成可信数字；新成功读数自动恢复。
- **上报输入边界（#276/#277）**：顶层 `observed_at` 必须是有效且显式带时区的 ISO 时间，
  非法值在业务写入前返回 `400/http_schema_invalid`。observed/ok 的成功额度必须显式提供
  有限百分比；真实 0/100、100/0、0/0 可接受，不增加必须相加为 100 的规则。失败占位仍
  可上传并显示缺失。新校验不修复假设存在的历史坏行；当前未认定生产发生过该输入事故。
- **设备显示名称（#226）**：由 Worker 的 `read-model/machine-names.ts` 统一维护和下发；
  Mac 客户端直接使用服务端标签。机器 ID、来源、OS 用户与权限仍独立，同名设备不合并。
- **出国时区方案（#186）**：macOS 菜单栏部分已合并（PR #197）——设备时区变化时额度悬停/标题栏/
  Server 更新时刻按本机时区显示并实时跟随系统时区切换，用量日界仍按北京时间（Asia/Shanghai）不变。
  iOS / Apple Watch 部分**未实施**，Issue #186 仍 OPEN。

> D1 体量等会随时间变化的数字不在此维护，需要时直接查。

## 有效决策

- **产品方向**：个人使用的多设备 AI usage 观测数据产品。
- **采集方向**：各终端在自己的 OS 用户上下文运行本机采集，主动 push 结构化 usage payload 到
  Cloudflare Worker；`ccusage` 只作日级对账和历史兜底，不应阻断 Codex / Claude Usage Ledger 明细上报。
- **展示方向（2026-09-27 用户决定，#199，未实施）**：产品只支持 macOS 菜单栏 popover 和 iPhone 端，
  Apple Watch 不急；Web dashboard（Worker 的 `/`、`/dashboard`、只供网页使用的 `/api/summary` 等
  接口与静态资源）整体废弃。Android、Windows 客户端方向随之搁置，不是当前工作范围。
  截至本次文档更新，`/api/summary`、Web 静态资源、旧口径路由代码**仍在仓库中，尚未删除**——
  这是决策，不是已完成的实现；`docs/product-brief.md` 中仍描述 Web dashboard 为「当前完整查看
  入口」的段落是**待清理的历史内容**，以本条决策为准。Mac 菜单栏与 iPhone 已经只读
  `/api/mobile/summary`。花费（`total_cost`）只在网页链路使用，采集端已于 2026-06-29 起不再上报
  花费字段；`/api/summary` 与 0014 rollup 的 `total_cost` 是否随 Web 废弃一并删除待 #199 落地时评估。
- **limits 原则**：历史 token / session logs 只做统计，不参与官方 reset time 计算。
- **Codex provider**：OAuth/WHAM usage 优先，`codex app-server` RPC `account/rateLimits/read` fallback。
- **Claude provider**：OAuth Usage API 优先，Claude CLI `/usage` fallback。
- **Antigravity provider**：已实现（`antigravity_limits_provider.py`、`mswusage_antigravity.py`），
  不是 `docs/product-brief.md` 里描述的「后续 spike」阶段；当前只看 Gemini 池，额度暂从 Mac
  本机读取，跨时区场景待研究（#182 记录了 TZ Antigravity 额度窗口曾为 unknown 的修复）。
- **#195（额度圆环新鲜度拆分重置时刻与已用%）**：原拆分与延长方案未实施，保留长期参考。
  #281 保持既有 120 分钟边界，仅增加明确带历史属性的失败降级，不等同于实施 #195。
- **服务端路径收敛**（#67，2026-08-02）：服务端收敛为 Cloudflare Worker + D1 **单实现**。
  采集端永远是 Python——它要读本机 ccusage / mswusage 与 OS 用户上下文，Worker 沙箱做不到，
  所以「采集端 ↔ 服务端」是一条**永久的跨语言边界**，只能治理不能消灭。
  决策全文与被否决选项的理由见 `docs/architecture/server-path-consolidation-decision.md`。
  - **职责判据**：只依赖本机可见输入的运算放采集端；需要跨设备全局视图的（汇聚、周期截断、
    归属守恒、额度窗口采用、健康判定）放 Worker；展示层零口径计算。
  - **事实层红线**：D1 必须保存满足已声明历史范围与重算精度所需的 canonical facts；
    rollup 与采集端预计算只是加速层。裁剪事实层必须先有保留期决策与会变红的守卫。
  - **采集端产出事实，不产出跨设备结论**；推送体不得只推预计算结果。
- **新字段的唯一去处**：`cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`。
  「Worker 加了、顺手在 Python 同步一份」是被明令禁止的——那正是让三种状态长期并存的机制。
- **执行规则**：所有开发任务 TDD；验证走 `scripts/verify.sh`（会按改动面自动裁剪，
  `--full` 强制全量，`--explain-scope` 查看判定依据）。

## 注意

- 不要把任务细节写回本文件，也不要在这里重建进度表。
- V1/V2 任务包体系已于 2026-08-01 整体归档，其文档已于 2026-08-02 删除（历史在 git）；
  新工作直接开 GitHub Issue，不再新增 `TP-V2-nnn` 编号。
- 既有 macOS Widget 文档只作历史/兼容资料，不是后续产品交付目标。
