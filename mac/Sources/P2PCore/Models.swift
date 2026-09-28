import Foundation

public struct DownloadTask: Codable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public let backend: String
    public var status: String
    public let progress: Double
    public let size: Int64
    public let speed: String
    public let sources: String
    public let path: String
    public let detail: String
    public var key: String { backend + ":" + id }
    public var isFinished: Bool { status == "complete" }
    public var canControl: Bool { ["active", "waiting", "paused"].contains(status) }
    public func deletionMessage(deleteFiles: Bool) -> String {
        if deleteFiles {
            return "该任务对应的已下载文件将移到废纸篓，包括未完成文件和续传数据。"
        }
        if backend == "ed2k" && !isFinished {
            return "仅移除任务。未完成的文件和续传数据会保留到恢复目录，删除后可以打开查看。"
        }
        return "仅移除任务，已下载的文件保留在原目录。"
    }
    public var statusTitle: String {
        switch status {
        case "active": return "正在下载"
        case "paused": return "已暂停"
        case "complete": return "已完成"
        case "verifying": return "正在校验"
        case "error": return "下载出错"
        case "unavailable": return "需要检查文件"
        case "removed": return "已移除"
        default: return size == 0 && backend == "bt" ? "等待磁力元数据" : "等待来源"
        }
    }
    public var sizeTitle: String {
        size > 0 ? ByteCountFormatter.string(fromByteCount: size, countStyle: .file) : "大小待确认"
    }
    public var progressTitle: String { String(format: "%.1f%%", min(100, max(0, progress))) }
    public var fraction: Double { min(1, max(0, progress / 100)) }
}

public struct EngineState: Codable, Identifiable {
    public let id: String
    public let name: String
    public let available: Bool
    public let running: Bool
    public let detail: String
    public let error: String?
    public var explanation: String {
        if error != nil { return "后台引擎控制连接异常，可查看详情。" }
        return running ? "引擎已运行，可接收任务；实际下载仍取决于来源。" : "后台引擎尚未运行，添加任务时会自动启动。"
    }
    public var title: String {
        if !available { return "未安装" }
        if error != nil { return "未就绪" }
        if !running { return "未启动" }
        if detail.contains("Not connected") || detail.contains("connecting") { return "连接中" }
        if detail.contains("LowID") { return "运行中 · LowID" }
        return "运行中"
    }
}

public struct BridgeReply: Codable {
    public var tasks: [DownloadTask]?
    public var engines: [EngineState]?
    public var folders: [String: String]?
    public var downloadSpeed: String?
    public let message: String?
    public let error: String?
    public let revealPath: String?
    public static let empty = try! JSONDecoder().decode(BridgeReply.self, from: Data("{}".utf8))
    public static let demo = try! JSONDecoder().decode(BridgeReply.self, from: Data(demoJSON.utf8))
}

public struct RemovalOptions {
    public var deleteFiles = false
    public init() {}
    public func payload(for item: DownloadTask) -> [String: String] {
        ["action": "remove", "backend": item.backend, "id": item.id,
         "delete_files": deleteFiles ? "true" : "false"]
    }
}

private let demoJSON = #"""
{
 "engines": [
   {"id":"ed2k","name":"eD2k","available":true,"running":true,"detail":"Connected with HighID"},
   {"id":"bt","name":"BitTorrent","available":true,"running":true,"detail":"就绪"}
 ],
 "downloadSpeed":"2.4 MiB/s",
 "tasks":[
   {"id":"demo-one","name":"Debian 13 · arm64.iso","backend":"bt","status":"active","progress":64.8,"size":4070000000,"speed":"2.4 MiB/s","sources":"18","path":"","detail":""},
   {"id":"demo-two","name":"公开数据集 · 气象观测 2025.zip","backend":"ed2k","status":"waiting","progress":12.5,"size":896000000,"speed":"","sources":"0 / 4","path":"","detail":"Waiting"},
   {"id":"demo-three","name":"Blender 开源示例场景.zip","backend":"bt","status":"complete","progress":100,"size":245000000,"speed":"","sources":"","path":"","detail":""}
 ]
}
"""#

public enum TaskFilter: String, CaseIterable {
    case all = "全部", active = "进行中", paused = "已暂停", complete = "已完成"
    public func matches(_ task: DownloadTask) -> Bool {
        switch self {
        case .all: return true
        case .active: return ["active", "waiting", "verifying"].contains(task.status)
        case .paused: return task.status == "paused"
        case .complete: return task.isFinished
        }
    }
}
