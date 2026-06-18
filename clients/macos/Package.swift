// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "AIUsageMenuBar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(name: "AIUsageMenuBarCore", targets: ["AIUsageMenuBarCore"]),
        .executable(name: "AIUsageMenuBar", targets: ["AIUsageMenuBarApp"])
    ],
    targets: [
        .target(name: "AIUsageMenuBarCore"),
        .executableTarget(
            name: "AIUsageMenuBarApp",
            dependencies: ["AIUsageMenuBarCore"]
        ),
        .testTarget(
            name: "AIUsageMenuBarCoreTests",
            dependencies: ["AIUsageMenuBarCore"],
            resources: [
                .process("Fixtures")
            ]
        ),
        .testTarget(
            name: "AIUsageMenuBarAppTests",
            dependencies: ["AIUsageMenuBarApp"]
        )
    ]
)
