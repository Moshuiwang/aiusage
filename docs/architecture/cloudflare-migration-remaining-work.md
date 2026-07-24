# Cloudflare 迁移收尾工作交接

> 本文件给接手的 AI Agent。迁移主体(回填→对账→repoint→稳定→切流)已完成;这里是剩余收尾工作。中文协作。

## 0. 一句话现状

生产入口 `https://aiusage.chunbai.com` 已**完全由 Cloudflare Native Worker + D1 提供服务**(读写都走 D1,D1 是权威库)。VPN2(`vpn2.chunbai.com:8443`,阿里云上的旧 Python 后端)的 **AI Usage 功能已下线**:入口 worker 已停止影子镜像写入 VPN2,VPN2 上的 `ai-usage-server.service` 已停止并禁用。VPN2 这台服务器可能仍承载其他功能,本次只下线 AI Usage 相关服务。

最终目标:**AI Usage 完全不需要 VPN2** —— 已完成。后续 `aiusage.chunbai.com` 的读写验收只看 Cloudflare/D1。

## 1. 不变量与底线(必须遵守)

- **数据不能丢;每一步可回退。** 任何破坏性操作前先备份。
- **采集只在本机 OS 用户上下文运行**;汇聚端只接受设备 push 的结构化 payload,不 SSH 拉原始日志。
- **官方额度可信度**:只有 `official==true && confidence=="observed" && status=="ok"` 才算可信官方额度。
- **展示层只读**:客户端不执行采集/不直连库重算口径。
- **验证"数据是否流入 D1" 要看 `usage_daily.last_seen_at` + 逐源 `total_tokens` 对账,不要看 `collection_runs`**(审计表只在采集报告内容变化时才写,空闲源不会更新,会误判)。
- 不提交 `data/`、`*.sqlite`、`config/*.local.json`、token、原始 usage 日志。未经用户明确同意不 `git commit`。

## 2. 访问方式(凭据只指位置,不含值)

- **Cloudflare**:真实账号操作只在 `/Users/wangzhipeng/Documents/ops` 中执行。先读取该目录的 `AGENTS.md`，由 Ops 选择受保护且具备目标资源权限的凭据；不读、不打印任何密钥值。
- **D1 查询**:由 Ops 在其受保护环境中执行只读查询；应用项目不得复制凭据或在本目录伪造账号侧结果。D1 的 UNION/compound SELECT 项数有限，拆短或用标量子查询。
- **SSH**:`~/.ssh/config` 已有 `vpn2`、`108.129.165.139`(eu-west EC2)。VPN2 的 canonical SQLite 在 `/home/ubuntu/ai-usage-widget/data/usage.sqlite`,只读访问可能需 `sudo -n`(`ssh vpn2 'sqlite3 -readonly <path> "<SQL>" || sudo -n sqlite3 -readonly <path> "<SQL>"'`)。
- **HTTP 直连 Native(workers.dev)**:本机有 HTTPS 代理且 workers.dev 有 BIC,curl 要 `env -u HTTPS_PROXY -u http_proxy ... curl -A "<浏览器UA>"`。生产入口 `aiusage.chunbai.com` 正常可达。
- **关键对象名**:入口 worker = `aiusage-api`(仓库根 `wrangler.toml`,代码 `cloudflare/aiusage-api-worker.js`,路由 `aiusage.chunbai.com/*`);Native worker = `aiusage-native-staging`(`cloudflare/native-worker/`,URL `https://aiusage-native-staging.chunbai.workers.dev`);D1 = `aiusage-prod-db`。
- 注意:仓库根 `wrangler.toml` 的 D1/KV/R2 绑定是 dev 资源,但入口 worker 代码不使用它们;`SHADOW_INGEST_URL` 是 secret(不在 toml,跨 deploy 保留)。

## 3. 切流回滚(随时可用)

把入口从 Native 切回 VPN2:
1. 仓库根 `wrangler.toml`:`ORIGIN_BASE_URL` 改回 `https://vpn2.chunbai.com:8443`。
2. `npx wrangler deploy`(global key 认证)。
3. `printf '%s' "https://aiusage-native-staging.chunbai.workers.dev" | npx wrangler secret put SHADOW_INGEST_URL --name aiusage-api`(影子写改回 D1)。
因 VPN2 一直热备=当前,回滚干净无损。

## 4. 剩余工作(逐项:目标 / 步骤 / 验收)

### A.【#7】VPN2 观察 → 下线  ★已完成,仅下线 VPN2 的 AI Usage 功能
- 目标:确认 D1/Native 在观察期稳定,然后正式停掉 VPN2。
- 步骤:
  1. 观察 N 天(用户定,建议 3–7 天)。每天:① `GET aiusage.chunbai.com` 的 `/`、`/login`、`/api/health`、`/api/mobile/summary?period=all` 正常(health 应 `status:ok`、`database:D1`);② D1 vs VPN2 逐源 `usage_daily` 的 `SUM(total_tokens)` 仍相等(证明热备在同步);③ 读 `docs/usage-fact-check-board.md`。
  2. 观察期无异常 + 用户批准后:先确认 VPN2 有完整数据备份;再停掉影子镜像(`SHADOW_INGEST_URL` 置空或指回 D1);最后停 VPN2 上的 ingest/server 服务并下线服务器。
- 验收:VPN2 的 AI Usage 后端停用后,`aiusage.chunbai.com` 一切照常、用户无感。这才是"AI Usage 完全不需要 VPN2"。注意:不要关停 VPN2 整机,该服务器还有其他功能。

### B.【#9】审计表保留策略
- 现状:回填只导了最近 14 天的 `collection_runs`/`source_reports`,但它们只增不减、会持续长大(D1 Free 单库上限 500MB)。
- 目标:保留最近 7 天(用户口径),并做成**周期性**清理。
- 步骤:① 一次性把 D1 的两表裁到 7 天(按外键序:先删 `source_reports` 或保证保留窗口内父子完整;只 D1,VPN2 不动);② 加一个周期任务(Native worker 的 Cron Trigger 或定时 wrangler 脚本)定期删 7 天外的行。
- 验收:两表始终 ≤7 天;`source health`(每源最新一条)与 `max(collected_at)` 新鲜度仍正确;D1 体积远低于 500MB。**禁止动 `usage_daily` 等业务数据表。**

### C.【#10】EC2 legacy 安全清理 ★真实凭据暴露
- 隐患:EC2(`108.129.165.139`)上 legacy 的 `ai-usage-pusher.service` systemd unit 里 `Environment=AI_USAGE_INGEST_TOKEN=...` **明文硬编码了 ingest token**(`/etc/systemd/system/` 下,可读目录的用户都能看到)。该 unit 已 disabled/inactive、被 `linux-wang` 取代。
- 步骤:① 轮换这个 ingest token —— 注意现在 ingest 入口是 Native worker,token 校验在 Native(`AIUSAGE_TOKEN`),轮换要**同时**更新 Native worker 的 token + 全部 5 个活跃 pusher 的 `/etc/ai-usage-widget/token.env`,协调好别让上报中断;② 删掉 legacy unit + 其 home 配置 `/home/wangzhipeng/ai-usage-widget/config/sources.local.json`。
- 验收:systemd unit 里无明文 token;5 个活跃 pusher 推送仍 `accepted`;legacy unit 已移除。

### D.【#5】设备截图核对(用户暂时跳过,可选补做)
- 目标:确认切流后 Mac 菜单栏 popover、iPhone、Apple Watch 显示的用量/额度正确。
- 注意:存在"读不到真机 App Group 缓存"的可观测性阻塞,见 §G 的文档。最低限度可比对设备拿到的 API 响应;完整屏幕核对需真机配合。

### E. source-health 差异决策
- 现象:切流后 dashboard 的设备健康列表比切流前少 4 个 —— 是 `VM-0-3-ubuntu` 那台已停用(06-02 后无数据,>14 天审计窗口外)死机器的源。**用量 total 不受影响**。
- 决策:① 接受(死机器,本就不该显示为活跃源)—— 推荐;或 ② 放宽审计窗口、把这些源的 `source_reports` 也回填进 D1。

### F.【#8】看板巡检
- 定期读 `docs/usage-fact-check-board.md`(由一个每 10 分钟跑的核查任务维护),把"建议修复/待办"里值得做的纳入工作列表。只读,别改它。

### G. iPhone/Watch 刷新可靠性(迁移后单独项目)
- 详见 `docs/product/iphone-watch-refresh-reliability-plan.md`。两段:Stage 1 本地证据/可观测性(客户端 iOS,与迁移无关);Stage 2 APNs 静默刷新(建在 **Cloudflare Worker** 上,切流后)。整项是迁移完成后的工作。

## 5. 工作纪律

- 机械活(D1 导入/计数/对账、wrangler 部署、SSH 改配置)**自己直接做**,做完**自己验证**(查 D1 / 比对 VPN2 / curl 生产),别只看"accepted"。
- 每个破坏性步骤前备份、可回退;触及生产配置的敏感操作先报告再做。
- 进度落到任务列表 + 本文件;与代码冲突以代码/测试为准。

## 6. 2026-06-24 接手进度

- 只读健康检查:生产入口 `/`、`/login` 返回 200;未登录 `/api/health` 和 `/api/mobile/summary` 返回 401,符合登录保护。带 Bearer 的本机 curl 超时,暂未作为健康证据。
- D1 vs VPN2 对账: `usage_daily` 行数均为 113,逐源 `SUM(total_tokens)` 全量一致,总量均为 6,666,356,477;D1 `MAX(last_seen_at)` 为 2026-06-24 10:35:57 CST,VPN2 为 2026-06-24 10:35:58 CST。
- B 审计表保留策略:本地已实现 Native Worker scheduled cleanup,只删除 7 天外的 `source_reports` 和 `collection_runs`,不碰 `usage_daily`;测试通过。尚未执行 D1 一次性删除,尚未部署 Cloudflare Cron,等用户确认。
- B 当前 D1 审计规模: `collection_runs` 15,091 行、`source_reports` 15,090 行,各有 7,833 行超过 7 天;当前 D1 size proxy 约 3.8MB,远低于 500MB。
- C EC2 legacy 安全清理:只读确认 legacy `ai-usage-pusher.service` 仍存在、inactive,且 unit 内仍有明文 `AI_USAGE_INGEST_TOKEN`;legacy home config 仍存在。5 个 `ai-usage-pusher-linux-*` timer 正在运行。尚未轮换 token、未删除文件,等用户确认。
- E source-health 差异: D1 当前 source identities 有 10 个,其中 `VM-0-3-ubuntu` 的 4 个旧源最后在 2026-06-02 上报;最新 `source_reports` 只有 6 个活跃源且均为 ok。建议接受 dashboard 不再显示死机器,不回填旧 source reports。
- F 看板巡检:已读 `docs/usage-fact-check-board.md`;当前主要缺口是 iPhone/Watch 设备证据不足、Cloudflare D1 额度窗口相对源站滞后。该项只读,未改看板。
- 12:18 刷新: D1 可读,`collection_runs` 15,195 行、`source_reports` 15,194 行,各有 8,470 行超过 7 天;最新 `collection_runs.max(collected_at)` 为 2026-06-24 12:13:33 CST。
- 12:18 对账: D1/VPN2 逐源 `SUM(total_tokens)` 仍一致;`mac-local` 最新 D1 last_seen_at 为 2026-06-24 12:13:33 CST,VPN2 为 2026-06-24 12:13:37 CST。Linux 活跃源 total 一致,但 D1 `usage_daily.last_seen_at` 仍不如 VPN2 新;D1 `source_reports` 显示 6 个活跃源均为 ok。
- 12:18 入口: `/`、`/login` 返回 200;带 Bearer 的 `/api/health` 和 `/api/mobile/summary?period=all` 仍超时,尚不能作为 A 观察期健康通过证据。B 清理后需重点复测这两项。
- 12:23 B 生产执行完成: 删除前已备份 D1 审计表到 `tmp/cloudflare-migration-b-backup-20260624-1219/`(`audit_tables.before.sql`、两表 JSON、删除前后 usage/source 基线)。D1 已裁剪 7 天外审计行,`source_reports` 删除 8,475 行,`collection_runs` 删除 8,475 行。
- 12:23 B 验收: `collection_runs` 6,726 行、`source_reports` 6,725 行,两表 7 天外行数均为 0;最新 6 个 source report 均为 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量为 6,683,973,457。
- 12:23 B 部署: Native Worker `aiusage-native-staging` 已部署 Cron Trigger `17 19 * * *`(北京时间每日 03:17),版本 `a174eb8e-99e0-47e3-89df-6a5176413abe`。生产 `/api/health` 和 `/api/mobile/summary?period=all` 带 Bearer 均恢复 200;`/api/health` 显示 `canonical_store=cloudflare_d1`、source status 6/6 ok。本地 Native Worker 测试 4 文件 22 例通过。
- 12:25 C 准备: 只读确认 EC2 legacy unit 和 legacy home config 仍存在,legacy unit 仍含明文 `AI_USAGE_INGEST_TOKEN`;5 个 EC2 pusher timer 正常。Cloudflare Native 当前只有 `AIUSAGE_TOKEN` secret。额外确认本机 `mac-local` runner 也内联使用 `AI_USAGE_INGEST_TOKEN`,因此 C 轮换范围必须包含 Native secret、EC2 5 个 pusher、本机 mac-local runner,否则 Mac 上报会断。
- 12:35 C 生产执行完成: 采用先双 token 兼容、再切新 token、最后移除兼容 secret 的方式轮换。Native Worker 现在仅保留 `AIUSAGE_TOKEN` secret;`AIUSAGE_TOKEN_SPECS` 已删除。EC2 `/etc/ai-usage-widget/token.env` 已更新且权限保持 0600/root:root;本机 `mac-local` runner、limits push env、macOS menu bar config、`cloud-flare/.env` 均已更新到新 token。
- 12:35 C legacy 清理: EC2 legacy `/etc/systemd/system/ai-usage-pusher.service` 和 `/home/wangzhipeng/ai-usage-widget/config/sources.local.json` 已从原路径移除,回退备份位于 EC2 root 目录 `/root/aiusage-legacy-cleanup-20260624042814/`。`systemctl` 扫描确认 legacy unit 缺失,5 个 `ai-usage-pusher-linux-*` timer 仍在运行。
- 12:35 C 热备补救: 轮换后发现 VPN2 热备 Python 服务仍校验旧 token,导致 shadow ingest 对 mac-local 暂时不同步;已同步更新 VPN2 `ai-usage-server.service` token 并重启服务。随后 mac-local usage/limits push 均 accepted,D1/VPN2 逐源 `SUM(total_tokens)` 重新一致,总量为 6,703,861,359。生产 `/api/health` 和 `/api/mobile/summary?period=all` 均 200,source status 6/6 ok。
- 12:35 C 客户端收口: macOS menu bar config 和 limits push URL 已从 `vpn2.chunbai.com:8443` 改为 `https://aiusage.chunbai.com`;用该 config token curl Cloudflare mobile summary 返回 200。临时本地 token 文件已删除。iPhone/Watch 仍属 D/G 的设备证据缺口,未在 C 中验证。
- 12:36 A 观察期巡检第 1 次: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 显示 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 一致,总量 6,703,861,359。看板仍有 iPhone/Watch 屏幕证据缺口和 Mac 菜单栏 quota 短暂滞后,需继续观察;VPN2 尚未获批下线。
- 12:43 A 观察期巡检第 2 次: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 一致,总量 6,705,091,830。D1 审计表补清滚动 7 天外小批过界行后,`collection_runs` 6,738 行、`source_reports` 6,737 行,两表 7 天外行数均为 0。看板 12:29 仍提示 iPhone/Watch 屏幕证据缺口和菜单栏 quota 短暂滞后;VPN2 尚未获批下线。
- 本轮续跑复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,710,227,480;`mac-local` 最新写入已推进到 12:40 CST。D1 审计表仍在 7 天窗口内,`collection_runs` 6,739 行、`source_reports` 6,738 行,两表 7 天外行数均为 0;最新 6 个 source report 均为 ok。看板最新记录 12:40 显示 Cloudflare/D1 额度窗口已追平源站主口径,持续缺口为 iPhone/Watch 屏幕证据不足和 Mac 菜单栏 Codex 缓存滞后;VPN2 尚未获批下线。
- 12:44 A 观察期巡检第 3 次: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok,`/api/mobile/summary?period=all` 全量 total 为 6,710,227,480。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,710,227,480;Linux 活跃源最新审计心跳推进到 12:42 CST,`mac-local` 最新业务写入为 12:40 CST。D1 审计表仍在 7 天窗口内,`collection_runs` 6,744 行、`source_reports` 6,743 行,两表 7 天外行数均为 0。看板仍是 12:40 结论:Cloudflare/D1 额度窗口已追平源站主口径,持续缺口为 iPhone/Watch 屏幕证据不足和 Mac 菜单栏 Codex 缓存滞后;VPN2 尚未获批下线。
- 12:45 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,710,227,480;D1 审计表仍为 `collection_runs` 6,744 行、`source_reports` 6,743 行,两表 7 天外行数均为 0。距离上次巡检仅约 1 分钟,无新增业务 token 增量属正常;VPN2 尚未获批下线。
- 12:46 A 观察期巡检第 4 次: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok,`/api/mobile/summary?period=all` 全量 total 为 6,717,724,425。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,717,724,425;`mac-local` 最新业务写入推进到 12:46 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,745 行、`source_reports` 6,744 行,两表 7 天外行数均为 0。看板仍是 12:40 结论,无新增迁移阻断;VPN2 尚未获批下线。
- 12:48 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,717,724,425;D1 审计表仍为 `collection_runs` 6,745 行、`source_reports` 6,744 行,两表 7 天外行数均为 0。距离 12:46 新写入约 2 分钟,无新增业务 token 增量属正常;VPN2 尚未获批下线。
- 12:49 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok,`/api/mobile/summary?period=all` 全量 total 为 6,717,724,425。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,717,724,425;Linux 活跃源最新审计心跳推进到 12:48 CST,`mac-local` 最新业务写入仍为 12:46 CST。D1 审计表仍在 7 天窗口内,`collection_runs` 6,750 行、`source_reports` 6,749 行,两表 7 天外行数均为 0。VPN2 尚未获批下线。
- 12:51 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,717,724,425;D1 审计表仍为 `collection_runs` 6,750 行、`source_reports` 6,749 行,两表 7 天外行数均为 0。看板 12:49 显示 Cloudflare/D1 继续追平源站主口径,无新增迁移阻断;VPN2 尚未获批下线。
- 12:52 A 观察期巡检第 5 次: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok,`/api/mobile/summary?period=all` 全量 total 为 6,731,342,993。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,731,342,993;`mac-local` 最新业务写入推进到 12:51 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,751 行、`source_reports` 6,750 行,两表 7 天外行数均为 0。VPN2 尚未获批下线。
- 12:54 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,731,342,993;D1 审计表仍为 `collection_runs` 6,751 行、`source_reports` 6,750 行,两表 7 天外行数均为 0。距离 12:52 巡检较近,无新增业务 token 增量属正常;VPN2 尚未获批下线。
- 12:55 A 观察期复核: 生产 4 个入口仍均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,source status 6/6 ok,`/api/mobile/summary?period=all` 全量 total 为 6,731,342,993。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,731,342,993;Linux 活跃源审计心跳推进到 12:54 CST,`mac-local` 最新业务写入仍为 12:51 CST。D1 审计表仍在 7 天窗口内,`collection_runs` 6,756 行、`source_reports` 6,755 行,两表 7 天外行数均为 0。VPN2 尚未获批下线。
- 12:59 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,738,843,216;`mac-local` 最新业务写入推进到 12:57 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,757 行、`source_reports` 6,756 行,两表 7 天外行数均为 0;最新 6 个 source report 均为 ok。VPN2 尚未获批下线。
- 13:00 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;mobile summary `period.total_tokens` 为 6,738,843,216。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,738,843,216;Linux 活跃源热备心跳推进到 13:00 CST,业务 token 总量暂无新增属正常短窗口现象。D1 审计表仍在 7 天窗口内,`collection_runs` 6,762 行、`source_reports` 6,761 行,两表 7 天外行数均为 0;最新 6 个 source report 均为 ok。看板 12:59 显示 Cloudflare/D1 已追平主口径,持续缺口仍是 Mac 菜单栏 Codex 缓存滞后和 iPhone/Watch 屏幕证据不足;VPN2 尚未获批下线。
- 13:03 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;mobile summary `period.total_tokens` 为 6,742,603,505。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,742,603,505;`mac-local` 最新业务写入推进到 13:02 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,763 行、`source_reports` 6,762 行,两表 7 天外行数均为 0;最新 6 个 source report 均为 ok。VPN2 尚未获批下线。
- 13:08 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;mobile summary `period.total_tokens` 为 6,745,824,535。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,745,824,535;`mac-local` 最新业务写入推进到 13:07-13:08 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,769 行、`source_reports` 6,768 行,两表 7 天外行数均为 0。VPN2 尚未获批下线。
- 13:12 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,mobile summary `period.total_tokens` 为 6,745,824,535。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,745,824,535;VPN2 热备心跳推进到 13:11 CST,业务 token 总量暂无新增属正常短窗口现象。D1 审计表仍在 7 天窗口内,`collection_runs` 6,774 行、`source_reports` 6,773 行,两表 7 天外行数均为 0。看板 13:09 显示 Cloudflare/D1 继续追平源站主口径,持续缺口仍是 Mac 菜单栏 Codex 缓存滞后和 iPhone/Watch 屏幕证据不足;VPN2 尚未获批下线。
- 13:14 A 观察期复核: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,mobile summary `period.total_tokens` 为 6,752,321,796。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,752,321,796;`mac-local` 最新业务写入推进到 13:13 CST,证明新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 6,775 行、`source_reports` 6,774 行,两表 7 天外行数均为 0。VPN2 尚未获批下线。
- 2026-06-25 12:48 A 观察期日巡检: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,mobile summary `period.total_tokens` 为 6,764,292,193。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,764,292,193;`mac-local` 最新业务写入推进到 12:46 CST,证明跨日新数据继续进入 D1 且热备同步。D1 审计表仍在 7 天窗口内,`collection_runs` 7,362 行、`source_reports` 7,361 行,两表 7 天外行数均为 0。看板 06:27 显示 Cloudflare 主站 API 与 D1 today tokens/额度主口径一致,Mac 菜单栏缓存仍有滞后但不阻塞迁移;VPN2 尚未获批下线。
- 2026-06-26 12:48 A 观察期日巡检: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,mobile summary `period.total_tokens` 为 6,599,374,103。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,599,374,103;D1 `usage_daily.max(last_seen_at)` 为 12:11 CST,VPN2 热备心跳推进到 12:43 CST,热备仍同步。D1 审计表仍在 7 天窗口内,`collection_runs` 7,538 行、`source_reports` 7,537 行,两表 7 天外行数均为 0。看板最新仍为 2026-06-25 06:27,当时 Cloudflare 主站 API 与 D1 today tokens/额度主口径一致;VPN2 尚未获批下线。
- 2026-06-27 12:48 A 观察期满 3 天日巡检: 生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`,mobile summary `period.total_tokens` 为 6,637,957,492。D1/VPN2 逐源 `SUM(total_tokens)` 仍一致,总量 6,637,957,492;D1 `usage_daily.max(last_seen_at)` 为 12:45 CST,VPN2 热备心跳推进到 12:47 CST,热备仍同步。D1 审计表仍在 7 天窗口内,`collection_runs` 7,708 行、`source_reports` 7,707 行,两表 7 天外行数均为 0。观察期从 2026-06-24 12:36 开始至今已满 3 天,期间生产入口、D1 业务写入、VPN2 热备同步、审计保留策略均无迁移阻断;下一步可向用户确认是否执行 VPN2 下线,未经确认不得停 VPN2。
- 2026-06-27 13:23 A 下线执行完成: 用户明确确认只下线 VPN2 的 AI Usage 功能,不影响 VPN2 其他功能。执行前已备份 VPN2 AI Usage SQLite 和 systemd unit 到 `/root/aiusage-shutdown-20260627132113/`。入口 Worker `aiusage-api` 已删除 `SHADOW_INGEST_URL` secret,停止向 VPN2 影子写入;VPN2 `ai-usage-server.service` 已 `inactive/disabled`,`ai-usage-backup.service` 仍为 inactive/static。验收:生产 `/`、`/login`、带 Bearer `/api/health`、`/api/mobile/summary?period=all` 均为 200;`/api/health` 仍为 `canonical_store=cloudflare_d1`;mobile summary、D1 `usage_daily` 总量均为 6,648,448,807,D1 最新业务写入推进到 13:18 CST;D1 审计表 `collection_runs` 7,751 行、`source_reports` 7,750 行,两表 7 天外行数均为 0;直连 `https://vpn2.chunbai.com:8443/login` 返回 502,符合 AI Usage 后端已停用预期。
