说中文

# Agent Rules

这是每次会话自动读取的最小硬规则，对所有 AI 编码代理（Codex、Claude Code 及后续替代工具）生效。
详细背景按需读取，不要把任务详情塞回本文件。

## 任务状态真值

**唯一真值是 GitHub**，不在仓库内维护第二份进度表：

- Issues：`gh issue list` / <https://github.com/Moshuiwang/aiusage/issues>
- Project #1 `AI Usage Delivery`：`gh project item-list 1 --owner Moshuiwang`
  代理需要维护的看板字段只有两个（2026-08-03 实测，`gh project field-list 1 --owner Moshuiwang`
  为准；其余都是 GitHub 内置字段，不用管）：
  - `Status`：`Backlog` / `Ready` / `In progress` / `Review` / `Waiting external` / `Done`
  - `证据等级`：`0 未开始` … `7 回源确认`，与下面「验证与证据」的等级同一套口径。
    读它时注意 `gh project item-list --format json` 会把**中文字段名的首字符编码搞坏**，
    按原名取永远是 `None`，要用后缀匹配（`endswith('据等级')`）

  **执行环境和工作类型不在看板上，改由 Issue 标签表达**（`gh label list` 为准）：

  - 执行环境：`env:linux` 本机可完成 / `env:mac` 必须 MacBook / `env:ops` 必须 Ops Agent /
    `env:device` 需真机。**领 Issue 前先看这个标签，不是你这台机器的直接别领。**
  - 工作类型：`bug` / `enhancement` / `refactor` / `guardrail` / `documentation` /
    `epic` / `plan`；`blocked` 表示开工条件未满足，`needs-decision` 表示等 PM 拍板。
  - 领域：`area:collector` / `area:worker` / `area:client-mac` / `area:client-ios` /
    `area:tooling` / `area:docs`。

开工先领取对应 Issue；研发 Agent 不负责维护 Project Status，同一变更只能有一个主实施代理。
新工作直接开 Issue，用产品语言描述用户结果。**V1/V2 任务包体系已于 2026-08-01 整体归档，
不要再新增 `TP-V2-nnn` 编号。**

## 验证与证据

- 验证入口 `scripts/verify.sh`（全量）/ `--python-only`（快速）。
  **收口口径（2026-08-03 起）：本地 targeted 测试绿 = 等级 3，全量套件交给 PR CI
  （合并唯一入口 `scripts/merge_pr.sh`，四个 check 全 SUCCESS 才执行；裸 `gh pr merge`
  被 bash_guard 拦截——免费私有仓库无服务端 branch protection，强制性在仓库内实现）。
  本地全量是可选复核，不是收口必要条件。**
  TDD 先红后绿与变异证据永远在本地做，CI 替代不了。细则见 `/verify`。
- 所有开发任务遵守 TDD：先写失败测试并确认它因目标行为缺失而失败，再实现最小代码。
  不得为了让测试通过而弱化断言、改预期值或缩小验收。
- 重构必须保持现有 API path、HTTP method、status code 和 JSON 合约不变。
- 汇报必须写明**证据等级**：1 已分析 / 2 已改代码 / 3 本地测试通过 / 4 CI 通过 / 5 已部署 /
  6 真机验证 / 7 回源确认。targeted 绿或 `verify.sh` 退出 0 都只等于第 3 级，**禁止用低一级证据宣称高一级完成**。
  未验证的层级必须明确列出。
- 不用「应该」「可能」「大概完成」代替事实；无法确认时明确写「未知」。

## 测试自身也会骗人

写实现的人和写测试的人是同一个，心智模型错了就会产出一对**自洽的错误**——测试全绿，
结论是错的。以下四条针对的就是这种情况，2026-08-01 与 2026-08-02 两次交付里各命中过至少一次。

- **守卫必须交付变异证据，不接受「现在是绿的」。** 新增断言、门禁、治理检查时，
  要实际破坏它守护的东西并贴出变红的输出。变异集要覆盖**绕过路径**而不只是正面路径
  （真出过这种事：治理断言只变异了相对导入，绝对导入能直接穿过去）。
  变异用文件备份还原，**不要用 `git checkout --`**，它会连未提交的改动一起冲掉。
- **golden 必须能自动发现自己陈旧。** 从某个实现生成的 golden，如果没有一条
  「重新生成并比对」的测试，它会在某天静默停止守护任何东西，而跨实现 parity 会因为
  「两边都没有新字段」继续报绿。
- **fixture 必须由 owner 模块产出，不许手写。** 手写 fixture 会和现实脱节，
  且脱节方向正好是「实现者以为的样子」——出现过 fixture 里带着读模型永远产不出的字段。
- **「通过」必须有结构下限，不能只看退出码或状态码。** 断言一件事成立时，同时断言它
  **确实检查了东西**：跑了几条、比了几个字段、拿到的结构里必须存在哪几个键。
  否则「什么都没检查」和「检查了且全过」产生同一个绿。真出过这些：parity 无结构下限；
  health 对「后端根本没返回版本块」判通过；302 登录页被判成健康；凭据守卫压根没执行到凭据路径；
  合同比对里 14/16 条只校 status 与 content-type，连「这条记录在 golden 里存不存在」都不查。
  **fixture 覆盖不到的场景等于没有断言**：断言的覆盖力受限于 fixture 的场景覆盖，
  缺一个场景就有一个盲区（出过：某字段只在一种失败形态下发送，而 fixture 没有那个场景，
  于是「顶层字段必须被声明并解析」的断言对它完全瞎）。

守恒等式、口径一致性这类不变量，核验时**从产物独立算一遍**，不要去跑被测代码自己的断言：
恒等式一旦选错对象（断言一个恒成立的式子），测试和实现会一起错。
执行现场机制见 `.claude/skills/tdd-task/SKILL.md`、`.claude/agents/reviewer.md` 和 `.codex/agents/reviewer.toml`。
**恒真断言要主动找**：凡是「断言某物不存在 / 为 None / 不在里面」的写法，先问一句——
在正确实现下它本来就不可能存在吗？是的话这条断言永远为真，删掉或换对象
（出过：断言一个条目里根本没有的 key 为 None；断言两个由同一构造产出的对象相等）。

**差异的路径名会骗人。** 比对结构时，某条差异叫 `items|len` 不代表它是「数量差」——
它可能是口径差穿过去重/聚合逻辑之后的投影。把差异归类成「已知的无害差异」之前，
**从两侧产物各自把那个值算出来看一眼**，不要照着路径名推断根因。

## 关键不变量（违反会破坏产品可信度）

- 每个 OS 用户只在自己的账户上下文运行采集；`wang` 不读 `/home/ubuntu`；
  不从 Mac 读取、同步或解析远程 `~/.claude`、`~/.codex` 原始日志目录。
- 汇聚端不通过 SSH 拉取，只接受设备 push 的结构化 payload。legacy 的 `collector.py` /
  SSH 拉取路径已随 #74 删除，不得复活。
- 官方额度：只有 `official == true && confidence == "observed" && status == "ok"` 才能当可信官方额度
  展示。`ccusage daily` / `blocks` 是本地估算，**不能伪装成官方额度**；`estimated` / `missing` /
  `unsupported` 必须降级展示。
- 展示层只读：客户端不执行采集、不直接读私表重算口径、不在平台侧重新聚合。
- daily token baseline 优先；limits/quota 只是可插拔 source。
- 本机和远程采集必须显式对齐时区。
- 不直接修改生产账户文件。

## 多机边界

本项目在多台机器上工作，能力不对等。**动手前先确认自己在哪台。**

| 机器 | 独有能力 |
| --- | --- |
| MacBook Air（`/Users/wangzhipeng/...`） | Xcode / `swift test` / `xcodebuild` / 模拟器 / 真机 / Watch；LaunchAgent 生产上报；Cloudflare Ops Agent（`/Users/wangzhipeng/Documents/ops`）；本地 skill `ai-usage-first-install` |
| Linux 开发机（`/home/...`） | Python 全量测试 + Cloudflare Native Worker 测试（需 Node 22） |

- 文档里出现 `/Users/wangzhipeng/...`、`codex exec --cd ...`、`swift`、`xcodebuild`、`xcodegen`
  的步骤都是 **macOS 专属**，其他机器不执行、也不因执行不了就判定为故障，
  直接标注「需回 Mac 侧执行」并列为验收缺口。
- 真实 Cloudflare 账号操作（部署、Secrets、路由、线上 smoke）只能由 Ops Agent 在 macOS 侧执行。
- 每台机器的本机事实（路径、运行时版本、已装能力、可用凭据）写在该机自己的
  `ENVIRONMENT.local.md`（`.gitignore` 已覆盖 `*.local.md`），**不要写进本文件**。

## 安全与提交

- 不提交 SSH key、token、原始 usage 日志、`config/*.local.json`、`data/`、`*.sqlite`、
  `latest.json` 或构建产物。
- 不读取、输出或记录凭据值；秘密不得进入聊天、命令参数、持久日志、Git、Issue 或 PR。
- 文档中不记录服务器公网 IP，主机名以 `~/.ssh/config` 为准。
- **没有用户明确要求，不得 `git add` / `git commit` / `git push`。**
- 提交身份用代理名而非本人姓名：`user.name` = 代理名，`user.email` = `<代理名>@<hostname>`，
  仓库级配置（不加 `--global`）。
- Git 提交、PR/MR 标题描述和用户可见收口默认使用中文。

## 事实源

**代码和测试是唯一事实源。** 文档（含架构文档、README、本文件）可能滞后；
如与代码冲突，以代码和测试为准并在报告里说明。

## 交付验收

iPhone / Apple Watch 交付不能只以 build、预检或安装成功为完成；
必须有用户可见启动和非空真实数据证据，设备不可用时明确写出验收缺口。

## 按需入口

- 当前事实与有效决策：`docs/status.md`
- 产品方向：`docs/product-brief.md`
- 工程架构：`docs/architecture/architecture.md`
- 项目地图：`docs/project-map.md`
- 项目命令：`README.md`

如果当前任务能用本文件和对应 Issue 完成，不要额外读取其他文档。
