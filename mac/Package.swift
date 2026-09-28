// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "P2PDownloads",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "P2PDownloads", targets: ["P2PDownloads"]),
               .executable(name: "P2PFileOps", targets: ["P2PFileOps"])],
    dependencies: [.package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.10.0")],
    targets: [
        .target(name: "P2PCore"),
        .executableTarget(name: "P2PDownloads", dependencies: ["P2PCore", .product(name: "Sparkle", package: "Sparkle")]),
        .executableTarget(name: "P2PFileOps"),
        .testTarget(name: "P2PCoreTests", dependencies: ["P2PCore"])
    ]
)
