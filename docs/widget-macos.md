# macOS Widget MVP

展示层有两个入口：

- `widget/macos/`：Swift Package 预览和核心逻辑测试。
- `widget/macos-xcode/`：真实 macOS App + WidgetKit extension 工程。

它们都只读取 `data/latest.json`，不执行 `ccusage`、SSH、collector，也不写入任何数据文件。

注意：真正的 WidgetKit extension 在 sandbox/container 中运行，不能直接读取仓库目录。collector 生成仓库内 `data/latest.json` 后，需要同步一份到 Widget container：

```bash
python -m ai_usage_widget.cli sync-widget --input data/latest.json
```

或者采集时直接同步：

```bash
python -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite \
  --sync-widget
```

## 运行预览

从仓库根目录运行：

```bash
cd widget/macos
swift run ai-usage-widget-preview
```

默认读取：

```text
~/Documents/ai-usage-widget/data/latest.json
```

如需指定快照路径：

```bash
AI_USAGE_LATEST_JSON=/absolute/path/to/latest.json swift run ai-usage-widget-preview
```

## 构建 WidgetKit App

第一次生成 Xcode 工程：

```bash
cd widget/macos-xcode
xcodegen generate
```

命令行构建：

```bash
xcodebuild -project AIUsageWidget.xcodeproj \
  -scheme AIUsageWidgetApp \
  -configuration Debug \
  -destination 'platform=macOS' \
  build
```

打开 Xcode：

```bash
open widget/macos-xcode/AIUsageWidget.xcodeproj
```

运行 `AIUsageWidgetApp` 后，系统会注册内嵌的 `AIUsageWidgetExtension`。随后可在 macOS Widget 添加界面里查找 `AI Usage`。

## 展示内容

- 今日总 tokens。
- 按机器、OS 用户、agent 拆分的今日 tokens。
- 最近采集时间。
- 成功 source 数量。
- 失败 source 状态。
- `latest.json` 缺失、损坏、今日无数据时的空态或错误态。

## 后续收敛

`widget/macos-xcode` 已接入 WidgetKit extension。后续需要收敛：

- 发布签名和正式 bundle id。
- 如果开启 App Sandbox，`latest.json` 迁移到 App Group container，或由宿主 App 导入到共享容器。
- quota/reset 数据源落地后，按 `docs/ui-direction/wight-ai-usage/` 改造 small / medium / large 视图。
- quota/reset 缺失、过期或仅估算时，继续保留 baseline daily usage 降级视图。
