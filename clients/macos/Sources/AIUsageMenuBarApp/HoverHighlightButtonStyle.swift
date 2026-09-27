import AppKit
import SwiftUI

/// #177 第四轮真机反馈：统一按钮点击手感——之前多处 `Button{}.buttonStyle(.plain)` 只有文字/
/// 图标的不透明像素可命中，行内空白、Spacer 区域点不中；且没有悬停/按下反馈，点中了也像没反应。
/// 按 Apple HIG：整块可点（contentShape）、悬停浅色高亮、按下有反馈；尊重「减少动态效果」时不做缩放。
struct HoverHighlightButtonStyle: ButtonStyle {
    let shape: AnyShape
    var pressedScale: CGFloat = 0.98

    init<S: Shape>(shape: S, pressedScale: CGFloat = 0.98) {
        self.shape = AnyShape(shape)
        self.pressedScale = pressedScale
    }

    func makeBody(configuration: Configuration) -> some View {
        HoverHighlightButtonLabel(configuration: configuration, shape: shape, pressedScale: pressedScale)
    }
}

/// #177 第四轮 Opus 审查：`@State` 从 `HoverHighlightButtonStyle` 本身移到这个独立的包装 View——
/// popover 的 hosting controller 常驻（只是 show/hide，不销毁重建），如果 popover 恰好在鼠标移出
/// 的同一瞬间关闭（窗口直接消失，不产生真正的 mouseExited 事件），`onHover(false)` 可能收不到，
/// 悬停状态会残留到下次打开。这里额外监听 `NSPopover.didCloseNotification` 主动复位，不依赖
/// `onHover` 一定会在关闭前收到退出事件。
private struct HoverHighlightButtonLabel: View {
    let configuration: HoverHighlightButtonStyle.Configuration
    let shape: AnyShape
    let pressedScale: CGFloat

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovered = false

    var body: some View {
        configuration.label
            .contentShape(shape)
            .background(shape.fill(Color.primary.opacity(backgroundOpacity)))
            .scaleEffect(scale)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: isHovered)
            .onHover { hovering in isHovered = hovering }
            .onReceive(NotificationCenter.default.publisher(for: NSPopover.didCloseNotification)) { _ in
                isHovered = false
            }
    }

    private var backgroundOpacity: Double {
        HoverHighlightAppearance.backgroundOpacity(isPressed: configuration.isPressed, isHovered: isHovered)
    }

    private var scale: CGFloat {
        HoverHighlightAppearance.scale(isPressed: configuration.isPressed, reduceMotion: reduceMotion, pressedScale: pressedScale)
    }
}

/// 纯函数外观计算——拆出来是为了能在不渲染 SwiftUI 的情况下单测（见 HoverHighlightAppearanceTests）。
enum HoverHighlightAppearance {
    static func backgroundOpacity(isPressed: Bool, isHovered: Bool) -> Double {
        if isPressed { return 0.12 }
        if isHovered { return 0.06 }
        return 0
    }

    static func scale(isPressed: Bool, reduceMotion: Bool, pressedScale: CGFloat) -> CGFloat {
        guard !reduceMotion, isPressed else { return 1.0 }
        return pressedScale
    }
}

extension ButtonStyle where Self == HoverHighlightButtonStyle {
    static func hoverHighlight<S: Shape>(_ shape: S) -> HoverHighlightButtonStyle {
        HoverHighlightButtonStyle(shape: shape)
    }
}
