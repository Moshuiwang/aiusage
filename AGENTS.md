说中文

# Agent Rules

每次会话自动读取的最小硬规则，对所有 AI 编码代理（Codex、Claude Code 及后续工具）生效。
任务真值在 GitHub Issue（`gh issue list`），不在仓库内维护第二份进度表；新工作直接开 Issue，
用产品语言描述用户结果；同一变更只能有一个主实施代理。

## 实现原则

- 明确废弃的接口、字段、调用路径和兼容层，确认无调用者后直接删除；不新增旧格式 migration
  或兼容 fallback。故障降级和用户可见的缺失状态不属于兼容层（见「关键不变量」的额度降级）。
- 用满足当前需求的最简实现，不做预防性抽象和多余配置层；先跑通最小端到端闭环再扩展。
- 引入新依赖前先查现有依赖。对外契约、数据边界和模块职责一次定型，不做明确需要未来重写的
  临时架构；重构必须保持现有 API path、HTTP method、status code 和 JSON 合约不变。

## 验证与证据

- 验证入口 `scripts/verify.sh`（全量）/ `--python-only`（快速）。收口口径：本地 targeted 测试绿 =
  等级 3，全量套件交给 PR CI；合并唯一入口 `scripts/merge_pr.sh`。细则见
  `.claude/skills/verify/SKILL.md`（Claude Code 用 `/verify`）。
- TDD：先写失败测试并确认它因目标行为缺失而失败，再实现最小代码；先红后绿与变异证据永远在
  本地做，CI 替代不了。不得为让测试通过而弱化断言、改预期值或缩小验收。
- 汇报写明证据等级：1 已分析 / 2 已改代码 / 3 本地测试通过 / 4 CI 通过 / 5 已部署 /
  6 真机验证 / 7 回源确认。禁止用低一级证据宣称高一级完成；未验证层级明确列出；
  无法确认时写「未知」。

## 测试自身也会骗人

实现和测试出自同一人，心智模型错了就会产出自洽的错误——全绿但结论错。
历史判例与操作细则见 `.claude/rules/tests.md`，写测试前先读。骨架四条：

- 新守卫必须交付变异证据：实际破坏被守护物、贴出变红输出；变异集要覆盖绕过路径。
- golden 必须有「重新生成并比对」的防陈旧测试；fixture 必须由 owner 模块产出，禁止手写。
- 「通过」必须有结构下限：同时断言跑了几条、比了哪些字段，否则「没检查」和「全过」同绿；
  fixture 覆盖不到的场景等于没有断言。
- 守恒与口径一致性从最终产物独立复算，不跑被测代码自己的断言；「断言某物不存在」的写法
  先自问是否恒真；差异归类为无害前，从两侧产物把值算出来，不照路径名推根因。

## 关键不变量（违反会破坏产品可信度）

- 每个 OS 用户只在自己账户上下文运行采集；不从 Mac 读取、同步或解析远程 `~/.claude`、
  `~/.codex` 原始日志目录。
- 汇聚端不通过 SSH 拉取，只接受设备 push 的结构化 payload；legacy `collector.py` / SSH 路径
  已随 #74 删除，不得复活。
- 只有 `official == true && confidence == "observed" && status == "ok"` 才能当可信官方额度展示；
  `ccusage daily` / `blocks` 是本地估算，不能伪装成官方额度；`estimated` / `missing` /
  `unsupported` 必须降级展示。
- 展示层只读：客户端不执行采集、不直接读私表重算口径、不在平台侧重新聚合。
- daily token baseline 优先，limits/quota 只是可插拔 source；本机和远程采集显式对齐时区。
- 线上承载于 Cloudflare Free 免费计划：设计与优化必须严守资源预算；客户端零短轮询、零无缓冲重复读，上报必 batch 批量写入；发布新版本后必须用 `scripts/check_cf_usage.py` 回源巡检用量水位（证据等级 7）。
- 不直接修改生产账户文件。

## 多机边界

- 动手前先确认自己在哪台机器；领 Issue 前先看 `env:` 标签（`gh label list` 为准），
  不是本机能做的别领。
- MacBook Air 独有：Xcode / `swift test` / 模拟器 / 真机 / Watch、LaunchAgent 生产上报、
  Cloudflare Ops Agent（真实部署、Secrets、线上 smoke 只能它做）。Linux 开发机：Python 全量 +
  Worker 测试（需 Node 22）。
- 文档里 `/Users/wangzhipeng/...`、`swift`、`xcodebuild` 类步骤是 macOS 专属：其他机器不执行、
  不判故障，标注「需回 Mac 侧执行」并列为验收缺口。本机事实见各机 `ENVIRONMENT.local.md`。
- iPhone / Watch 交付不以 build 或安装成功为完成，必须有用户可见启动和非空真实数据证据。

## 安全与提交

- **没有用户明确要求，不得 `git add` / `git commit` / `git push`。**
- 不读取、输出或记录凭据值；秘密不进聊天、命令参数、日志、Git、Issue 或 PR；
  文档不记录服务器公网 IP。
- 提交身份用代理名（仓库级 config，不加 `--global`）；提交、PR 标题描述和收口默认中文。

## 事实源与按需入口

**代码和测试是唯一事实源**；文档可能滞后，冲突时以代码为准并在报告里说明。
当前事实 `docs/status.md` · 产品方向 `docs/product-brief.md` · 架构
`docs/architecture/architecture.md` · 项目地图 `docs/project-map.md` · 命令 `README.md`。
能用本文件和对应 Issue 完成的任务，不要额外读其他文档。
