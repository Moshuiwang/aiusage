# iOS Current Wireframe

这个目录是当前 iOS App 的低保真复原线稿，用于产品评审和后续高保真收敛。

## 预览

```bash
cd docs/prototypes/ios-current-wireframe
python3 -m http.server 8786 --bind 127.0.0.1
```

打开：

```text
http://127.0.0.1:8786/index.html
```

## 可交互范围

- 底部四个标签：首页、来源、明细、额度。
- 首页周期切换：今天、周、月、全部。
- 首页趋势图：点击或拖动显示当前点提示。
- 首页快捷入口：查看明细、查看额度、查看来源。
- 明细页：维度切换和行点击下钻。
- 额度页：重置提醒开关。

## 边界

- 这是线稿，不是最终视觉。
- 不连接生产数据。
- 不修改真实 iOS SwiftUI 代码。
