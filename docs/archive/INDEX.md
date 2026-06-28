# Archive Index

这里保存历史执行记录、已弃用路线、过期设计稿和评审记录。归档内容用于追溯，不作为当前实现或当前产品方向的权威来源。

AI Agent 默认不要读取本目录；只有用户要求查历史、回溯决策或审计旧任务包时再进入。

## 当前权威入口

- 项目地图：[`../project-map.md`](../project-map.md)
- 当前架构：[`../architecture/architecture.md`](../architecture/architecture.md)
- 当前数据库：[`../architecture/database.md`](../architecture/database.md)
- 当前接口：[`../architecture/interfaces.md`](../architecture/interfaces.md)
- 当前任务包：[`../task-packages/v2/INDEX.md`](../task-packages/v2/INDEX.md)

## 归档分区

| 分区 | 内容 |
| --- | --- |
| `task-packages/v1/` | 已弃用的 SSH pull / macOS Widget-first 路线。 |
| `task-packages/v2/completed/` | V2 已完成任务包。当前索引仍在 `docs/task-packages/v2/INDEX.md`。 |
| `task-packages/v2/cancelled/` | 已撤销、不再执行的 V2 任务包（如 TP-V2-062，被 TP-V2-073~080 取代）。 |
| `task-packages/v2/assets/` | 已完成任务包引用过的归档素材。 |
| `design/` | 过期或阶段性设计稿，包括多端设计包、客户端边界旧文档、UI 方向素材。 |
| `prototypes/` | 历史原型代码和 handoff。 |
| `proposals/` | 已降级为历史参考的 account-hourly usage 方案。 |
| `legacy/` | legacy Widget 和旧展示方案。 |
| `reviews/` | 历史 AI review 记录。 |
| `governance/` | 旧 harness 规则和治理参考。 |
| `handoff/` | 历史交接文档。 |
| `plans/` | 已被任务包吸收的旧计划。 |

## 清理说明

当前根部 `reviews/` 和 `docs/reviews/` 不作为文档入口保留；临时 review 请求和中间报告应在任务完成后删除。需要追溯历史评审时，只读本目录下的 `reviews/` 归档。

`docs/prototypes/*` 在原位置保留 symlink 指针，用于兼容现有原型测试；真实内容在本归档区。
