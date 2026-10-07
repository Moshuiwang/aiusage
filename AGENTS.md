说中文

# Agent Rules

对所有 AI 编码代理（Codex、Claude Code 等）生效的最小硬规则。**代码和测试是唯一事实源**；
文档可能滞后，冲突时以代码为准并在报告里说明。

## 任务与协作

- 任务真值在 GitHub Issue；建卡、改标签或 Milestone 前读
  [Issue 治理规范 #233](https://github.com/Moshuiwang/aiusage/issues/233)。新工作用产品语言描述用户结果。
- 同一变更只能有一个主实施代理。
- **没有用户明确要求，不得 `git add` / `git commit` / `git push`。** 提交身份用代理名（仓库级 config，
  不加 `--global`）；提交、PR 与收口默认中文。

## 实现原则

- 明确废弃的接口、字段、兼容层，确认无调用者后直接删除；不新增旧格式 migration 或兼容 fallback。
  故障降级和用户可见的缺失状态不属于兼容层。
- 用满足当前需求的最简实现，不做预防性抽象；引入新依赖前先查现有依赖。
  重构保持 API path、HTTP method、status code 和 JSON 合约不变。

## 验证与证据

- 验证入口 `scripts/verify.sh`；合并唯一入口 `scripts/merge_pr.sh`（CI 四项全 SUCCESS 才合并）。
- 先写失败测试并确认它因目标行为缺失而失败，再实现；新守卫要贴出「破坏被守护物 → 变红」的变异证据。
  不得为让测试通过而弱化断言、改预期值或缩小验收。
- fixture / golden 由 owner 模块生成，禁止手写；守恒与口径一致性从最终产物独立复算。
- 汇报写明证据等级：1 已分析 / 2 已改代码 / 3 本地测试通过 / 4 CI 通过 / 5 已部署 /
  6 真机验证 / 7 回源确认。不用低一级证据宣称高一级完成，未验证层级明确列出，无法确认写「未知」。

## 关键不变量（违反会破坏产品可信度）

- 每个 OS 用户只在自己账户上下文采集；不读取、同步或解析其他机器的 `~/.claude`、`~/.codex` 原始日志。
  汇聚端只接受设备 push 的结构化 payload，不通过 SSH 拉取。
- 只有 `official == true && confidence == "observed" && status == "ok"` 才能当可信官方额度展示；
  `ccusage` 与校准估算是本地估算，不能伪装成官方额度；`estimated` / `missing` / `unsupported` 必须降级展示。
- 展示层只读：客户端不执行采集、不直接读私表重算口径、不在平台侧重新聚合。
- daily token baseline 优先，limits/quota 只是可插拔 source；本机和远程采集显式对齐时区。
- 线上承载于 Cloudflare Free：严守资源预算，客户端零短轮询、零无缓冲重复读，上报必须 batch；
  发布新版本后用 `scripts/check_cf_usage.py` 回源巡检用量水位（证据等级 7）。
- 不直接修改生产账户文件。

## 机器职责

- 动手前确认自己在哪台机器；领 Issue 前看 `env:` 标签，不是本机能做的别领。
- MacBook Air：Xcode / XCTest / 模拟器 / 真机 / Watch、LaunchAgent 生产上报。
- Mac mini：本机开发与菜单栏验证；用户 2026-10-04 授权承担 Cloudflare 部署、Secrets 与线上 smoke。
- Linux：Python 全量 + Worker 测试（Node 22）。`/Users/...`、`swift`、`xcodebuild` 类步骤在其他机器标注
  「需回 Mac 侧执行」并列为验收缺口。本机事实见各机 `ENVIRONMENT.local.md`。
- iPhone / Watch 交付不以 build 或安装成功为完成，必须有用户可见启动和非空真实数据证据。

## 凭据与生产

- 不读取、输出或记录凭据值；秘密不进聊天、命令参数、日志、Git、Issue 或 PR；文档不记录服务器公网 IP。
- Mac mini 的 Cloudflare 凭据经 Ops BWS 入口按需注入本次进程，用法见
  `/Users/wangzhipeng/Documents/project/ops/projects/ai-usage/bws-cloudflare.md`。
  入口可用不等于写操作已授权：生产写操作按对应 Issue 授权逐项判断，并留回滚点。

## 事实源

当前事实 `docs/status.md` · 产品方向 `docs/product-brief.md` · 架构 `docs/architecture/architecture.md` ·
项目地图 `docs/project-map.md` · 命令 `README.md`。
