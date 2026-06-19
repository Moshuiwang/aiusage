import SwiftUI

public struct AIUsageBrandMark: View {
    private let size: CGFloat
    private let cornerRatio: CGFloat

    public init(size: CGFloat = 44, cornerRatio: CGFloat = 0.225) {
        self.size = size
        self.cornerRatio = cornerRatio
    }

    public var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * cornerRatio, style: .continuous)
                .fill(
                    RadialGradient(
                        colors: [
                            Color(red: 30 / 255, green: 32 / 255, blue: 53 / 255),
                            Color(red: 12 / 255, green: 13 / 255, blue: 24 / 255)
                        ],
                        center: UnitPoint(x: 0.35, y: 0.30),
                        startRadius: 0,
                        endRadius: size * 0.74
                    )
                )

            Circle()
                .stroke(BrandColor.claudeOrange.opacity(0.18), lineWidth: size * 0.11)
                .frame(width: size * 0.76, height: size * 0.76)
            Circle()
                .trim(from: 0, to: 0.70)
                .stroke(BrandColor.claudeOrange, style: StrokeStyle(lineWidth: size * 0.11, lineCap: .round))
                .frame(width: size * 0.76, height: size * 0.76)
                .rotationEffect(.degrees(-90))

            Circle()
                .stroke(BrandColor.openaiBlue.opacity(0.18), lineWidth: size * 0.09)
                .frame(width: size * 0.40, height: size * 0.40)
            Circle()
                .trim(from: 0, to: 0.45)
                .stroke(BrandColor.openaiBlue, style: StrokeStyle(lineWidth: size * 0.09, lineCap: .round))
                .frame(width: size * 0.40, height: size * 0.40)
                .rotationEffect(.degrees(-90))

            Circle()
                .fill(Color.white.opacity(0.65))
                .frame(width: size * 0.07, height: size * 0.07)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("AI Usage")
    }
}

public enum BrandColor {
    public static let claudeOrange = Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255)
    public static let claudePeach = Color(red: 234 / 255, green: 168 / 255, blue: 130 / 255)
    public static let openaiBlue = Color(red: 10 / 255, green: 132 / 255, blue: 1)
    public static let openaiCyan = Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)
}
