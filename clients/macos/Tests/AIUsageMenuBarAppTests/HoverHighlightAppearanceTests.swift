import XCTest
@testable import AIUsageMenuBarApp

/// #177 第四轮 Opus 审查：HoverHighlightButtonStyle 的外观计算拆成纯函数，
/// 不需要渲染 SwiftUI 就能锁住「按下优先于悬停」「减少动态效果时不缩放」等分支。
final class HoverHighlightAppearanceTests: XCTestCase {
    func testBackgroundOpacityPrioritizesPressedOverHovered() {
        XCTAssertEqual(HoverHighlightAppearance.backgroundOpacity(isPressed: true, isHovered: true), 0.12)
        XCTAssertEqual(HoverHighlightAppearance.backgroundOpacity(isPressed: true, isHovered: false), 0.12)
    }

    func testBackgroundOpacityHoveredWithoutPressed() {
        XCTAssertEqual(HoverHighlightAppearance.backgroundOpacity(isPressed: false, isHovered: true), 0.06)
    }

    func testBackgroundOpacityIdleIsZero() {
        XCTAssertEqual(HoverHighlightAppearance.backgroundOpacity(isPressed: false, isHovered: false), 0)
    }

    func testScaleAppliesPressedScaleOnlyWhenPressedAndMotionAllowed() {
        XCTAssertEqual(HoverHighlightAppearance.scale(isPressed: true, reduceMotion: false, pressedScale: 0.98), 0.98)
    }

    func testScaleStaysAtOneWhenNotPressed() {
        XCTAssertEqual(HoverHighlightAppearance.scale(isPressed: false, reduceMotion: false, pressedScale: 0.98), 1.0)
    }

    /// 减少动态效果时即使按下也不缩放。
    func testScaleIgnoresPressedWhenReduceMotionEnabled() {
        XCTAssertEqual(HoverHighlightAppearance.scale(isPressed: true, reduceMotion: true, pressedScale: 0.98), 1.0)
    }
}
