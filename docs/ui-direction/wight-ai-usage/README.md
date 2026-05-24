# Wight for AI Usage UI Direction

## 用途

这里归档 `Wight for AI Usage.zip` 中导出的 UI 设计稿，作为本项目后续 UI 视觉方向的参考资产。

该设计稿不是当前 SwiftUI WidgetKit 的直接实现代码。它是 React + Babel 的静态设计原型，用来表达目标信息架构、视觉风格和多尺寸 Widget 形态。

## 文件

- `source.zip`：原始下载包归档。
- `index.html`：可在浏览器中打开的设计入口。
- `widgets.jsx`：Widget 视觉组件、mock 数据和图表组件。
- `design-canvas.jsx`：设计画布、缩放、分组和 artboard 展示工具。

本地预览：

```bash
cd docs/ui-direction/wight-ai-usage
python3 -m http.server 8765 --bind 127.0.0.1
```

然后打开：

```text
http://127.0.0.1:8765/index.html
```

注意：页面依赖 unpkg CDN 加载 React、ReactDOM 和 Babel，离线时可能不能渲染。

## 可采纳方向

- Apple-style Widget 视觉风格：圆角、磨砂玻璃、浅色/深色、foreground/background 四态。
- small / medium / large 三种尺寸的信息密度分层。
- Agent 使用颜色区分，source / host 使用独立色板区分。
- 大号 Widget 可以承载 token 结构、source 分布和趋势类图表。
- Widget 应该优先展示关键状态，而不是变成完整 dashboard。

## 当前 baseline 可直接支持的部分

当前 `latest.json` 可以支撑：

- 今日 total tokens。
- 今日 input / output / cache creation / cache read token 类型拆分。
- 按 machine / account / agent 分组。
- 最近采集时间。
- source 成功/失败状态。

这些内容可以映射到设计稿中的主数字、分组列表、source 区域和部分堆叠条。

## 超出当前 baseline 的部分

设计稿中的这些内容需要 snapshot v1、历史聚合或 limits source 后才能实现：

- 5H quota 百分比。
- week quota 百分比。
- reset time / reset date。
- 官方 usage percentage。
- 15m / 60m / 7d / 30d 切换。
- Widget 内趋势图。
- Gemini、DeepSeek、GitHub Actions 等额外 provider/source。

当前 `ccusage daily --json` 只提供 daily token/cost/history 视角，不能直接提供官方 quota、reset window 或 usage percentage。实现这些内容需要新增 limits source 或其他可靠数据来源，不能用 token history 伪装成官方额度状态。

## 落地原则

后续 SwiftUI / WidgetKit 实现可以吸收设计稿的视觉和布局，但必须先完成 snapshot contract，并做好数据降级：

- `5H/WK/%/reset` 在数据源未补齐前不展示。
- 主展示改为今日 token 和 token 类型结构。
- source 失败状态必须保留，不能被视觉稿中的 mock hosts 替代。
- 历史趋势如需进入 Widget，应由 collector 预聚合写入 `latest.json`，Widget 不直接读 SQLite。
