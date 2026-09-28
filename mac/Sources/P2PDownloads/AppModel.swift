import AppKit
import SwiftUI
import P2PCore
import UniformTypeIdentifiers

@MainActor
final class AppModel: ObservableObject {
    @Published var snapshot = BridgeReply.empty
    @Published var isRefreshing = false
    @Published var isBusy = false
    @Published var busyMessage = "正在处理，首次启动引擎可能需要一分钟…"
    @Published var feedback: String?
    @Published var error: String?
    @Published var showAdd = false
    @Published var link = ""
    @Published var output = UserDefaults.standard.string(forKey: "outputDirectory") ?? ""
    @Published var filter = TaskFilter.all
    @Published var lastUpdated: Date?
    @Published var pendingDeletion: DownloadTask?
    @Published var retainedFilesPath: String?
    var panelVisible = false { didSet { if timer != nil { scheduleRefresh() } } }
    @Published var language: AppLanguage = AppLanguage(rawValue: UserDefaults.standard.string(forKey: "appLanguage") ?? "system") ?? .system
    var l: L10n {
        let preferred = UserDefaults.standard.persistentDomain(forName: UserDefaults.globalDomain)?["AppleLanguages"] as? [String]
        return L10n(language.resolved(preferred: preferred ?? Locale.preferredLanguages))
    }
    func setLanguage(_ value: AppLanguage) {
        language = value
        guard !demo else { return }
        UserDefaults.standard.set(value.rawValue, forKey: "appLanguage")
        if value == .system { UserDefaults.standard.removeObject(forKey: "AppleLanguages") }
        else { UserDefaults.standard.set([value.rawValue], forKey: "AppleLanguages") }
    }
    let demo: Bool
    let updater: AppUpdater
    private let client: BridgeClient
    private var timer: Timer?
    var tasks: [DownloadTask] { snapshot.tasks ?? [] }
    var filteredTasks: [DownloadTask] { tasks.filter(filter.matches) }
    var activeCount: Int { tasks.filter { TaskFilter.active.matches($0) }.count }

    init() {
        let arguments = CommandLine.arguments
        demo = !arguments.contains("--live") && (arguments.contains("--demo") || arguments.contains("--render-preview"))
        updater = AppUpdater(enabled: !demo)
        let base = Bundle.main.resourceURL ?? Bundle.main.bundleURL
        client = BridgeClient(script: base.appendingPathComponent("p2p/gui_bridge.py"),
                              stateDirectory: ProcessInfo.processInfo.environment["P2P_STATE_DIR"])
        if let index = arguments.firstIndex(of: "--language"), arguments.count > index + 1,
           let chosen = AppLanguage(rawValue: arguments[index + 1]) { language = chosen }
        if demo {
            snapshot = .demo
            showAdd = arguments.contains("--preview-add")
        }
    }

    func start() {
        guard !demo, timer == nil else { return }
        refresh()
        scheduleRefresh()
    }

    private func scheduleRefresh() {
        timer?.invalidate()
        let interval: TimeInterval = panelVisible ? 5 : 60
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refresh()
            }
        }
        timer?.tolerance = interval / 5
    }

    func refresh() {
        guard !demo, !isRefreshing, !isBusy else { return }
        isRefreshing = true
        Task {
            defer { isRefreshing = false; lastUpdated = Date() }
            do { snapshot = try await client.request(["action": "snapshot"]) }
            catch { self.error = error.localizedDescription }
        }
    }

    func perform(_ payload: [String: String], clearInput: Bool = false) {
        guard !isBusy else { return }
        if demo { feedback = "这是界面预览，未执行下载操作。"; return }
        isBusy = true
        busyMessage = "正在处理，首次启动引擎可能需要一分钟…"
        error = nil
        feedback = nil
        retainedFilesPath = nil
        Task {
            do {
                let response = try await client.request(payload)
                feedback = response.message
                retainedFilesPath = response.revealPath
                if clearInput { link = ""; showAdd = false }
            } catch { self.error = error.localizedDescription }
            isBusy = false
            refresh()
        }
    }

    func addLink() {
        let source = link.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !source.isEmpty else { return }
        perform(["action": "add", "source": source, "output": output], clearInput: true)
    }

    func remove(_ task: DownloadTask, options: RemovalOptions) {
        guard !isBusy else { return }
        if demo {
            snapshot.tasks?.removeAll { $0.key == task.key }
            feedback = "已移除示例任务，未操作实际文件。"
            return
        }
        perform(options.payload(for: task))
    }

    @discardableResult
    func acceptDrop(_ providers: [NSItemProvider]) -> Bool {
        guard !providers.isEmpty else { return false }
        guard !isBusy else {
            error = "正在处理上一项操作，请完成后再拖入。"
            return false
        }
        isBusy = true
        busyMessage = "正在读取拖放内容…"
        error = nil
        feedback = nil
        let destination = output
        Task {
            let batch = await DropSources.read(providers)
            var errors = batch.errors
            var added = 0
            if demo {
                feedback = l.format("已识别 %d 个项目；预览模式未执行下载。", batch.sources.count)
            } else {
                for (index, source) in batch.sources.enumerated() {
                    busyMessage = l.format("正在添加 %d / %d，首次启动可能需要一分钟…", index + 1, batch.sources.count)
                    do {
                        _ = try await client.request(["action": "add", "source": source, "output": destination])
                        added += 1
                    } catch { errors.append(l.format("第 %d 项：%@", index + 1, l.text(error.localizedDescription))) }
                }
                if added > 0 { feedback = l.format("已添加 %d 个下载任务。", added) }
            }
            if !errors.isEmpty {
                let prefix = added > 0 ? l.format("已添加 %d 个任务；其余项目需要处理：\n", added) : ""
                self.error = prefix + errors.prefix(5).map { l.text($0) }.joined(separator: "\n")
                    + (errors.count > 5 ? l.format("\n另有 %d 项未能添加。", errors.count - 5) : "")
            }
            isBusy = false
            refresh()
        }
        return true
    }

    func importTorrent() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "torrent") ?? .data]
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.prompt = l.text("添加种子")
        if panel.runModal() == .OK, let url = panel.url {
            perform(["action": "add", "source": url.path, "output": output])
        }
    }

    func chooseDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.prompt = l.text("选择下载目录")
        if panel.runModal() == .OK, let url = panel.url {
            output = url.path
            UserDefaults.standard.set(output, forKey: "outputDirectory")
        }
    }

    func reveal(_ task: DownloadTask) {
        let path = task.path.isEmpty ? (snapshot.folders?[task.backend] ?? output) : task.path
        guard let destination = FinderDestination.resolve(path: path) else {
            error = "下载目录不可用，请确认磁盘已连接。"
            return
        }
        if destination.selectFile { NSWorkspace.shared.activateFileViewerSelecting([destination.url]) }
        else { NSWorkspace.shared.open(destination.url) }
    }

    func openFolder() {
        let path = output.isEmpty ? (snapshot.folders?["ed2k"] ?? NSHomeDirectory() + "/Downloads/P2P") : output
        let url = URL(fileURLWithPath: path)
        if FileManager.default.fileExists(atPath: path) { NSWorkspace.shared.open(url) }
        else { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Downloads")) }
    }
}
