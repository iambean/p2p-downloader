import Combine
import Foundation
import Sparkle
import SwiftUI

@MainActor
final class AppUpdater: ObservableObject {
    private let controller: SPUStandardUpdaterController
    private var observations: Set<AnyCancellable> = []
    @Published private(set) var canCheck = false
    @Published private(set) var automatic = true

    init(enabled: Bool) {
        controller = SPUStandardUpdaterController(startingUpdater: enabled, updaterDelegate: nil, userDriverDelegate: nil)
        controller.updater.publisher(for: \.canCheckForUpdates)
            .receive(on: RunLoop.main).sink { [weak self] in self?.canCheck = enabled && $0 }.store(in: &observations)
        controller.updater.publisher(for: \.automaticallyDownloadsUpdates)
            .receive(on: RunLoop.main).sink { [weak self] in self?.automatic = $0 }.store(in: &observations)
    }

    func check() { controller.checkForUpdates(nil) }
    func setAutomatic(_ value: Bool) {
        controller.updater.automaticallyChecksForUpdates = value
        controller.updater.automaticallyDownloadsUpdates = value
    }

    var version: String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "v\(info["CFBundleShortVersionString"] as? String ?? "开发版") (\(info["CFBundleVersion"] as? String ?? "—"))"
    }
}

struct UpdateMenuItems: View {
    @ObservedObject var updater: AppUpdater
    var body: some View {
        Button("检查更新…") { updater.check() }.disabled(!updater.canCheck)
        Toggle("自动下载并安装更新", isOn: Binding(get: { updater.automatic }, set: updater.setAutomatic))
        Text("Apple Silicon · \(updater.version)")
    }
}
