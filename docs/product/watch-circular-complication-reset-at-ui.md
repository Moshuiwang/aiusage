# Watch Circular Complication Reset At UI

## 目标

Apple Watch 圆形小组件用于让用户抬腕快速判断两类额度窗口状态：

- Codex 额度
- Cloud / Claude 额度

本版重点不是显示倒计时，而是显示 5 小时窗口的 **Reset At 本地时间**。用户看到的是“这一轮 5 小时额度在手表当前时区的几点重置”。

## 设计稿

当前确认稿的用户可见规则以本文为准。早期视觉稿保留为辅助参考：

- PNG 预览：`tmp/design/watch-complication-circular-mock.png`
- HTML / SVG 源稿：`tmp/design/watch-complication-circular-mock.html`

![Watch circular complication Reset At UI](../../tmp/design/watch-complication-circular-mock.png)

设计稿同时覆盖：

- 45mm / 49mm 圆形小组件实际尺寸参考，约 `50pt ~= 100px`
- 41mm 安全尺寸参考，约 `44.5pt ~= 89px`
- Codex 正常状态
- Codex 无 reset_at 状态
- Cloud 正常状态
- Cloud 无 reset_at 状态

开发时以本文的信息层级、圆环间距、中心时间大小、缺失状态和 stale 状态为准。HTML / SVG 源稿仅用于后续微调或重新导出图片，不作为 PR 唯一验收来源。

## 信息层级

圆形小组件中心只放最关键的信息：

1. Reset At 本地时间，主视觉，例如 `14:48`
2. 账号短名，次要小字，例如 `WHAM`、`TEAM`

如果 41mm 真机上出现拥挤，优先保留 Reset At 时间，账号短名可以移除。

## 显示规则

### Reset At 时间

数据源提供的是 `reset_at`，它是具体重置时刻，不是剩余倒计时。

Watch 端展示时：

- 将 `reset_at` 转成 Apple Watch 当前时区
- 只显示时间，不显示日期
- 使用 24 小时制
- 固定格式为 `HH:MM`

示例：

- `reset_at = 2026-06-03T06:48:52+00:00`
- 手表当前时区为 UTC+8
- 小组件显示 `14:48`

即使重置时间是次日，也不显示日期，只显示转换后的本地时间。

### 缺失状态

当没有可信 5 小时窗口、`reset_at` 缺失、或时间解析失败时，中心时间显示：

```text
--:--
```

不显示空白，不显示错误文本，不显示 stale 作为时间替代。

### Stale 状态

当 Watch 本地缓存已经 stale 时，圆形小组件必须保留可见 stale 信号。旧缓存可以继续展示最后一次成功的 Reset At 和额度环，但不能看起来像实时数据。

推荐展示：

- 中心仍优先保留 `HH:MM` 或 `--:--`
- 辅助小字显示 `STALE`
- 圆环降低不透明度

## 圆环规则

圆形小组件保留双环：

- 外圈：5 小时窗口使用百分比
- 内圈：长窗口使用百分比

本版视觉要求：

- 外圈尽量贴近圆形小组件外边界
- 内圈比上一版更靠近外圈
- 内圈线宽收细，给中心 `HH:MM` 留出安全空间
- 中心 `HH:MM` 不允许压住或贴住内圈圆环
- 当 5 小时窗口缺失、不可信、或不是 official/observed/ok 时，外圈显示为空/降级态，不能用长窗口补位
- 当长窗口缺失或不可信时，内圈显示为空/降级态，不影响外圈 5 小时槽位

## 颜色规则

Codex：

- 外圈蓝色
- 内圈浅蓝色

Cloud / Claude：

- 外圈暖橙色
- 内圈浅暖橙色

两者布局一致，只通过颜色和账号短名区分。

## 文案规则

圆形小组件内部不显示：

- `Codex`
- `Cloud`
- `5H Reset`
- 日期
- 倒计时

中心只显示账号短名和 Reset At 时间。

## 验收标准

实现后至少确认：

- 45mm / 49mm 尺寸下，账号短名和 `HH:MM` 清晰可读
- 41mm 尺寸下，`HH:MM` 不压住内圈圆环
- Codex 和 Cloud 使用同一套布局
- Codex 和 Cloud 颜色可区分
- `reset_at` 按手表当前时区显示
- 缺失或解析失败时显示 `--:--`
- stale summary 有可见 stale 信号，旧数据不能伪装成实时
- 5 小时窗口缺失或不可信时，外圈不挪用长窗口
- 如果小尺寸拥挤，移除账号短名后仍保留 `HH:MM`
