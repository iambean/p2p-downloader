import Foundation

public enum BridgeFailure: LocalizedError {
    case message(String)
    public var errorDescription: String? {
        switch self { case .message(let text): return text }
    }
}

public struct BridgeClient {
    public let script: URL
    public let stateDirectory: String?
    public init(script: URL, stateDirectory: String? = nil) {
        self.script = script
        self.stateDirectory = stateDirectory
    }
    public func request(_ payload: [String: String]) async throws -> BridgeReply {
        let script = self.script
        let state = self.stateDirectory
        let input = try JSONSerialization.data(withJSONObject: payload)
        return try await Task.detached(priority: .utility) {
            let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            guard let python = candidates.first(where: FileManager.default.isExecutableFile(atPath:)) else {
                throw BridgeFailure.message("未找到 Python 3。请先安装 Python 3，再重新打开应用。")
            }
            guard FileManager.default.fileExists(atPath: script.path) else {
                throw BridgeFailure.message("应用的下载组件缺失，请重新构建或安装应用。")
            }
            let process = Process()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [script.path] + (state.map { ["--state-dir", $0] } ?? [])
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (environment["PATH"] ?? "")
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process.environment = environment
            let output = Pipe(), stdin = Pipe()
            process.standardOutput = output
            process.standardError = output
            process.standardInput = stdin
            try process.run()
            let timeout = DispatchWorkItem { if process.isRunning { process.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + 150, execute: timeout)
            defer { timeout.cancel() }
            stdin.fileHandleForWriting.write(input)
            try? stdin.fileHandleForWriting.close()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let text = String(decoding: data, as: UTF8.self)
            // Bootstrap progress is stderr text; the protocol response is the final JSON line.
            guard let line = text.split(separator: "\n").last,
                  let result = try? JSONDecoder().decode(BridgeReply.self, from: Data(line.utf8)) else {
                throw BridgeFailure.message(process.terminationReason == .uncaughtSignal
                    ? "操作超时。下载引擎可能仍在启动，请查看日志。" : "下载组件未返回有效结果。\n" + String(text.suffix(1500)))
            }
            if let error = result.error { throw BridgeFailure.message(error) }
            guard process.terminationStatus == 0 else { throw BridgeFailure.message("下载组件异常退出。") }
            return result
        }.value
    }
}
