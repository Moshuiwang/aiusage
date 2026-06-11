// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "AIUsageMobile",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(name: "AIUsageMobileCore", targets: ["AIUsageMobileCore"])
    ],
    targets: [
        .target(name: "AIUsageMobileCore"),
        .testTarget(
            name: "AIUsageMobileCoreTests",
            dependencies: ["AIUsageMobileCore"],
            resources: [
                .process("Fixtures")
            ]
        )
    ]
)
