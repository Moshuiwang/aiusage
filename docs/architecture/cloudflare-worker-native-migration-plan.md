# Cloudflare Worker Native 迁移规划（草案）

> 面向产品经理。讲清楚现状、目标、边界、风险和验收，不展开底层实现。
> 本文为规划草案，不代表已实施；实施需另开任务包并遵守 TDD。

---

## 0. 一句话背景

今天用户打开的是 `aiusage.chunbai.com`（Cloudflare 域名），但这只是“门面”。真正干活的后端还是 VPN2 上那台 Python 服务。本规划要回答：**怎么把后端真正搬进 Cloudflare，让 VPN2 可以退役，而用户全程无感。**

一个关键认知先摆在最前面：**采集（数据从哪来）和后端（数据存哪、怎么算、怎么给客户端看）是两件事。** Cloudflare 只能接管后端，永远接管不了采集，因为采集必须发生在每台机器、每个系统账号的本地上下文里。这条边界决定了整个迁移的形状。

---

## 1. 当前状态

### 1.1 用户看到的 vs 真实发生的

- 用户、iPhone、Watch、Dashboard、macOS 客户端访问的都是 `https://aiusage.chunbai.com`。
- 这个域名背后是一个 Cloudflare Worker，但它**只是一个反向代理（穿透转发）**，自己不存数据、不算数据。
- 它把所有请求原样转发回 `https://vpn2.chunbai.com:8443`，也就是真实的 Python 后端。
- 所以**现在如果 VPN2 挂了，整个产品就挂了**，Cloudflare 这层挡不住。

### 1.2 Cloudflare 当前承担的能力（仅这些）

| 能力 | 说明 |
| --- | --- |
| 统一入口域名 | 用户只认 `aiusage.chunbai.com`，不再暴露 VPN2 地址 |
| 路径白名单 | 只放行 `/`、`/dashboard`、`/login`、`/static/*`、`/api/*`、`/ingest`、`/ingest-limits`，其它一律 404 |
| 反向代理回源 | 把请求转发到 VPN2，并补 `X-Forwarded-Host/Proto` 头 |
| 边缘 TLS | 在 Cloudflare 侧终结 HTTPS |
| 缓存策略 | 强制 `no-store`，并按 `Authorization`/`Cookie` 区分，避免缓存串号 |

**重要诚实点**：配置里已经声明了 D1 数据库、KV、R2 三个资源（`wrangler.toml`），但当前 Worker 代码**完全没用它们**。也就是说，资源已经开好了，但还是“空跑”状态，一行业务逻辑都没在 Cloudflare 侧执行。

### 1.3 VPN2 当前承担的能力（真正的后端全在这）

| 能力 | 对应代码 |
| --- | --- |
| 登录 / 会话 Cookie | `server.py` |
| Token 鉴权（设备 Bearer / 网页 Cookie） | `server.py` |
| 接收设备上报用量 `/ingest` | `server_services.py` |
| 接收额度上报 `/ingest-limits` | `server_services.py` |
| 唯一权威数据库（SQLite） | `storage_sqlite.py` |
| 读模型快照 `latest.json` | `snapshot_builder.py` |
| 网页摘要 `/api/summary` | `snapshot_builder.py` |
| 移动端摘要 `/api/mobile/summary` | `mobile_summary.py` |
| 健康检查 `/api/health` | `server_services.py`（看本地文件） |
| Dashboard 网页和静态资源 | `server.py` 读本地 `static/` 目录 |

### 1.4 采集（不在 VPN2，也不在 Cloudflare）

容易被忽略的一层：**真正的数据来源在每台设备本机**，不在 VPN2，更不在 Cloudflare。

- 每台机器、每个系统账号本地跑 `ccusage`（daily/session/blocks）和 `mswusage-codex`，再主动 push 到后端。
- 额度数据由本机读取 `~/.codex/auth.json`、`~/.claude` 相关文件，调官方 API、跑 `codex app-server`、`claude /usage` 命令拿到，再 push。
- 这些靠 macOS LaunchAgent / Linux systemd / Windows 计划任务定时触发。

VPN2 从来都只是“收数据的中心”，不是“采数据的人”。这点对理解迁移边界极其重要。

---

## 2. 目标状态

- 用户、iPhone、Watch、Dashboard、macOS 客户端**只访问 `aiusage.chunbai.com`**，且这个域名背后就是完整后端，不再回源 VPN2。
- 中心后端由 **Cloudflare Worker Native** 承担：登录、鉴权、上报、读摘要、健康检查全部在 Cloudflare 上跑。
- **D1 成为唯一权威数据库**（替代 VPN2 上的 SQLite 文件）。
- KV / R2 / Queues / Cron / Secrets **按需使用**：
  - Secrets 存 token 和会话密钥；
  - KV 或 R2 可选用于缓存预算好的摘要、存放静态资源；
  - Queues / Cron 可选用于异步重算摘要、定时维护。
- **各设备本地采集器原样保留**。这是产品的硬边界：Cloudflare 没有也不可能有用户本机的系统账号上下文，跑不了 `ccusage`、读不了本地 Codex/Claude 文件。采集永远在设备侧，Cloudflare 只接收它们 push 上来的结构化数据。

迁移成功后的状态用一句话概括：**设备照旧采集照旧上报，只是“上报到哪、数据存哪、谁来算”从 VPN2 换成了 Cloudflare，用户全程看不出区别。**

---

## 3. 可迁移能力分类

这是整个规划的核心判断。分三类。

### 3.1 可以迁到 Worker Native 的（搬过去能用）

| 能力 | 迁移要点 |
| --- | --- |
| `/ingest` 接收用量 | 业务逻辑清晰，改成写 D1 |
| `/ingest-limits` 接收额度 | 同上 |
| `/api/summary` 网页摘要 | 聚合逻辑可翻译，改成查 D1 |
| `/api/mobile/summary` 移动摘要 | 本质是对 summary 做字段裁剪，最容易迁 |
| `/api/health` 健康检查 | 需要换判断口径（见 3.2） |
| 登录 / 会话 | 改用 Worker + Secrets |
| Dashboard 入口与静态资源 | 改由 R2 / Worker 静态资源托管 |
| summary / mobile 的 DTO 生成 | 纯数据变换，迁移成本低 |

### 3.2 必须改写的（不能照搬，要换实现方式）

| 当前实现 | 为什么不能照搬 | 改写方向 |
| --- | --- | --- |
| Python HTTPServer（`BaseHTTPRequestHandler`） | Cloudflare 上没有这种常驻进程模型 | 改写成 Worker 的请求处理 |
| SQLite 文件访问（WAL、busy_timeout、`ALTER TABLE` 自迁移） | Cloudflare 上没有本地文件系统 | 改用 D1，SQL 方言要逐条核对 |
| `latest.json` 文件快照（原子写文件、读文件） | 没有本地磁盘可写可读 | 改为查询时即时计算，或用 KV/R2 缓存 |
| 每次请求落临时文件再读回来 | 当前 summary/mobile 每次请求都在磁盘写一个临时文件再读出来 | 改为内存里直接从 D1 结果算出来 |
| `/api/health` 看本地文件 | 现在靠“数据库文件多大、快照文件什么时候改的”判断健康 | 改为看 D1 里的最近上报时间、行数等元数据 |

### 3.3 不能迁的（永远留在设备侧）

| 能力 | 为什么不能迁 |
| --- | --- |
| `ccusage` 本地采集 | 需要每个系统账号自己的 `~/.claude` 上下文 |
| `mswusage-codex` 采集 | 需要读本机 `~/.codex/sessions` 原始日志 |
| 本机 auth 文件读取 | `~/.codex/auth.json`、`~/.claude` 只存在于设备上 |
| codex app-server proxy | 需要在本机起子进程跑 CLI |
| Claude / Codex CLI fallback | 同上，`claude /usage`、`codex` 命令在本机 |
| macOS LaunchAgent / systemd / 计划任务调度 | 定时触发只能在设备操作系统里做 |

**这一类是迁移的天花板**：无论 Cloudflare 多强，它都拿不到用户本机的账号上下文。所以“摆脱 VPN2”指的是摆脱中心后端那台机器，**不是**摆脱设备采集。采集器照旧装在每台设备上。

---

## 4. 推荐技术路线

**推荐：用 TypeScript Worker 作为主路线。不推荐把现有 Python 服务原封不动搬成 Python Worker。**

原因（从稳定性和运维角度，不展开代码）：

1. **生态成熟度**：Cloudflare 的 Workers、D1、KV、R2、Secrets、Cron、Queues 这一整套，对 TypeScript/JS 的支持最成熟、文档最全、部署链路最稳。Python Worker 相对新，冷启动更重，和 D1 等绑定的配合不如 TS 顺。
2. **照搬本来就不成立**：现有 Python 代码强依赖“本地 SQLite 文件 + 常驻 HTTPServer 进程 + 本地磁盘写快照”。这三样在 Cloudflare 上都不存在。所以即使勉强上 Python Worker，也**必须重写**这部分——既然都要重写，不如用生态更顺的 TS。
3. **Python 不是白写的**：现有 Python 逻辑（数据口径、聚合规则、额度可信度判定、idempotent upsert key、错误脱敏）是**最权威的业务规格说明书和测试基准**。迁移时拿它当“标准答案”，逐步翻译成 TS，并用现有 fixture 做新旧一致性比对。

一句话：**Python 留作“规则与测试参照”，TS 做“新后端实现”，两边用同一批 fixture 校验口径一致。**

---

## 5. 分阶段迁移方案

每个阶段都遵守“先红后绿”的测试纪律，且**不动生产**直到明确的切换阶段。

### Phase 0：只读盘点与合同测试补齐
- 把现有 API 的输入输出、字段、错误码固化成“合同测试”（用 fixture 重放，不依赖真实数据）。
- 目的：为后面“新后端必须和老后端一模一样”建立可机器验证的基准线。
- **不碰生产、不写新功能。**

### Phase 1：D1 schema 与迁移策略设计（不切生产）
- 设计 D1 表结构，逐条核对和现有 SQLite 的差异。
- 设计历史数据从 SQLite 导入 D1 的方式与校验口径。
- 产出文档和脚本草案，**仍不切生产**。

### Phase 2：TS Worker 实现只读 API（用测试数据）
- 先实现 `/api/summary`、`/api/mobile/summary` 的只读路径，从 fixture / D1 测试库返回数据。
- 用 Phase 0 的合同测试验证：新 Worker 的输出和老 Python 输出逐字段一致。

### Phase 3：实现写入 `/ingest` 和 `/ingest-limits`（写 D1）
- Worker 接收设备 push，写入 D1。
- **保留 VPN2 双写或影子写**：同一份上报同时进老库和 D1，便于比对，且任何时刻都能回退。

### Phase 4：Cloudflare 与 VPN2 结果对比
- 同样的查询，分别打到 Cloudflare 和 VPN2，逐字段比对。
- 用真实设备验证 Dashboard / iPhone / Watch 体验完全一致。
- 这是“敢不敢切”的决策门。

### Phase 5：切流到 Worker Native（不再回源 VPN2）
- 把 `aiusage.chunbai.com` 的后端正式指向 D1 版 Worker，停止回源 VPN2。
- 用户无感；出问题可快速回退到代理模式。

### Phase 6：VPN2 降级或下线
- 观察一段时间确认稳定后，VPN2 降为备份，或正式下线。

---

## 6. 验收标准

切换是否成功，用下面这些用户可见的事实来判定，不靠“代码看起来对了”。

- [ ] iPhone App 能拉到**非空的生产数据**（不是占位、不是空壳）。
- [ ] Dashboard 登录正常、静态资源（CSS/JS）正常加载、summary 正常显示。
- [ ] `/ingest` 和 `/ingest-limits` 能被**真实设备** push 成功。
- [ ] D1 里的数据与原 SQLite **口径一致**（不是大概一致，是逐项对得上）。
- [ ] 今日 / 周 / 月 / all 四个周期，machine / account 过滤，limits / quota 展示，**和切换前一致**。
- [ ] Watch / iOS / macOS 读取 `/api/mobile/summary` **不退化**（字段、刷新、stale 语义都在）。
- [ ] **关停 VPN2 后，用户入口仍然可用**——这是“真正摆脱 VPN2”的最终证据。

---

## 7. 风险

| 风险 | 说明 | 应对方向 |
| --- | --- | --- |
| **D1 额度与限制** | 免费额度对存储量、每日读写行数、查询有上限；当前每次 ingest 都重算快照的做法在 Worker 上会放大读写成本 | 评估额度；把“每次写都重算”改成“查询时算”或异步重算 |
| **SQLite → D1 的 SQL 差异** | 现有代码用了 WAL、busy_timeout、`executescript`、`ALTER TABLE` 自迁移、临时表搬迁等本地特性，D1 不一定支持 | Phase 1 逐条核对，能力不对齐的要换写法 |
| **快照缓存策略变化** | 现在 Worker 强制 `no-store`；若改成 KV/R2 预算缓存以省 D1 查询，必须设计“上报后及时失效”，否则用户看到旧数据 | 明确缓存失效触发点 |
| **登录 / 会话迁移** | 会话 Cookie 是用一个密钥签出来的；密钥若换，老用户的登录态会失效需要重新登录。设备 / iOS 的 Bearer token 也要原样进 Secrets | 决定是否沿用原密钥（沿用则用户无感）；token 提前配好 |
| **ingest 幂等与重复上报** | 同一设备/日期/agent 重复上报靠稳定 key 去重。D1 的 upsert 行为必须和 SQLite 完全对齐，否则会重复计数或漏更新 | 用现有 fixture 专门测幂等 |
| **额度 / provider 数据采不到** | quota 必须在设备本机采集后 push，Cloudflare 侧采不了 | 维持设备 push 链路不变，别误以为后端能自己拉额度 |
| **客户端残留配置** | 切换过程中 iOS / Watch / macOS 可能残留旧 base URL、旧 token、旧缓存，导致验收误判 | 切换前清点客户端配置；用真机而非缓存验收 |

---

## 附：一个容易踩的认知误区

“迁到 Cloudflare 后是不是就不用每台机器装采集了？”——**不是。** Cloudflare 接管的是“中心后端”，采集永远在设备本机。这次迁移不会减少设备侧的任何东西，减少的只是 VPN2 这台中心服务器的依赖。把这点说清楚，能避免后面对“为什么还要在每台机器维护采集脚本”的反复疑问。
