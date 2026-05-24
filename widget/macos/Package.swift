// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "AIUsageWidget",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(name: "AIUsageWidgetCore", targets: ["AIUsageWidgetCore"]),
        .executable(name: "ai-usage-widget-preview", targets: ["AIUsageWidgetPreview"]),
        .executable(name: "ai-usage-widget-check", targets: ["AIUsageWidgetCheck"])
    ],
    targets: [
        .target(name: "AIUsageWidgetCore"),
        .executableTarget(
            name: "AIUsageWidgetPreview",
            dependencies: ["AIUsageWidgetCore"]
        ),
        .executableTarget(
            name: "AIUsageWidgetCheck",
            dependencies: ["AIUsageWidgetCore"]
        ),
        .testTarget(
            name: "AIUsageWidgetCoreTests",
            dependencies: ["AIUsageWidgetCore"]
        )
    ]
)
