# iOS High Fidelity Prototype

这是基于 `docs/prototypes/ios-current-wireframe/` 确认后的高保真原型。线稿目录保留不变，本目录用于后续 iOS 开发对齐视觉和交互。

开发交接入口：[HANDOFF.md](HANDOFF.md)。

## 页面结构

- 首页：今天 / 周 / 月，总用量、Input、Output、Cache、缓存命中、趋势图、刷新时间。
- 额度：三个账号额度窗口，展示订阅名称、统计时间、周额度、5 小时额度和刷新时间。
- 明细：默认 Date，维度顺序为 Date / Machine / User / Model / Agent；月度 Date 按日期倒序。
- 来源：采集来源列表和状态。

## 本地查看

```bash
python3 -m http.server 8787 --directory docs/prototypes/ios-high-fidelity
```

然后打开：

```text
http://127.0.0.1:8787/index.html
```

## 验证

```bash
node --check docs/prototypes/ios-high-fidelity/app.js
node docs/prototypes/ios-high-fidelity/smoke-test.mjs
```
