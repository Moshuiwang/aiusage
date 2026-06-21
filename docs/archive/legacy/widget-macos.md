# macOS Widget

## 定位

macOS Widget 是展示面，只读 snapshot，不拥有采集逻辑。

展示层有两个入口：

- `widget/macos/`：Swift Package 预览和核心逻辑测试。
- `widget/macos-xcode/`：真实 macOS App + WidgetKit extension 工程。

它们都不执行 `ccusage`、SSH、collector，也不写入数据文件。

## Snapshot 同步

真正的 WidgetKit extension 在 sandbox/container 中运行，不能直接读取仓库目录。collector 生成仓库内 `data/latest.json` 后，需要同步一份到 Widget container：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli sync-widget --input data/latest.json
```

或者采集时直接同步：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite \
  --sync-widget
```

后续工程化收敛时，App Group container 路径必须在 Python sync 和 Swift SnapshotLoader 两侧有测试。

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

## 测试

Swift core 任务默认先跑：

```bash
cd widget/macos
swift test
```

WidgetKit 工程任务再跑：

```bash
cd widget/macos-xcode
xcodegen generate
xcodebuild -project AIUsageWidget.xcodeproj \
  -scheme AIUsageWidgetApp \
  -configuration Debug \
  -destination 'platform=macOS' \
  build
```

## 展示内容

Baseline UI：

- 今日总 tokens。
- token 类型结构。
- 按机器、OS 用户、agent 拆分的今日 tokens。
- 最近快照生成时间。
- source health。
- `latest.json` 缺失、损坏、过期、今日无数据时的空态或错误态。

Limits UI：

- 只有 snapshot 中存在可信 `limits` 时才展示。
- observed limits 可以显示 5h / week 进度和 reset time。
- estimated limits 必须弱化。
- missing / unsupported / failed 时降级到 baseline UI。

## 后续收敛

- Swift 解码 `latest.json` v1。
- small / medium / large 三种 Widget family 信息密度分层。
- App Group container 路径固定。
- 发布签名和正式 bundle id。
- 视觉风格向 `docs/ui-direction/wight-ai-usage/` 收敛。
