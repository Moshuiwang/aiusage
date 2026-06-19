import SwiftUI

public struct AIUsageBrandMark: View {
    private let size: CGFloat

    public init(size: CGFloat = 44) {
        self.size = size
    }

    public var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                .fill(
                    RadialGradient(
                        colors: [
                            Color(red: 45 / 255, green: 49 / 255, blue: 72 / 255),
                            Color(red: 20 / 255, green: 24 / 255, blue: 39 / 255),
                            Color(red: 7 / 255, green: 9 / 255, blue: 16 / 255)
                        ],
                        center: UnitPoint(x: 0.34, y: 0.27),
                        startRadius: 0,
                        endRadius: size * 0.88
                    )
                )

            AIUsageRingArc(startAngle: -96, endAngle: 157)
                .stroke(Color.white.opacity(0.10), style: StrokeStyle(lineWidth: size * 0.09, lineCap: .round))
                .frame(width: size * 0.70, height: size * 0.70)
            AIUsageRingArc(startAngle: -96, endAngle: 157)
                .stroke(Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255), style: StrokeStyle(lineWidth: size * 0.09, lineCap: .round))
                .frame(width: size * 0.70, height: size * 0.70)

            AIUsageRingArc(startAngle: -90, endAngle: 124)
                .stroke(Color.white.opacity(0.11), style: StrokeStyle(lineWidth: size * 0.076, lineCap: .round))
                .frame(width: size * 0.38, height: size * 0.38)
            AIUsageRingArc(startAngle: -90, endAngle: 124)
                .stroke(Color(red: 10 / 255, green: 132 / 255, blue: 1), style: StrokeStyle(lineWidth: size * 0.076, lineCap: .round))
                .frame(width: size * 0.38, height: size * 0.38)

            Circle()
                .fill(Color.white.opacity(0.84))
                .frame(width: size * 0.11, height: size * 0.11)
            Circle()
                .fill(Color(red: 10 / 255, green: 132 / 255, blue: 1))
                .frame(width: size * 0.035, height: size * 0.035)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("AI Usage")
    }
}

private struct AIUsageRingArc: Shape {
    let startAngle: Double
    let endAngle: Double

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.addArc(
            center: CGPoint(x: rect.midX, y: rect.midY),
            radius: min(rect.width, rect.height) / 2,
            startAngle: .degrees(startAngle),
            endAngle: .degrees(endAngle),
            clockwise: false
        )
        return path
    }
}
