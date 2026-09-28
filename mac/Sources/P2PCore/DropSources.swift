import Foundation
import UniformTypeIdentifiers

public struct DropBatch {
    public var sources: [String] = []
    public var errors: [String] = []
    public init() {}
}

public enum DropSources {
    public static let types = [UTType.fileURL.identifier, UTType.url.identifier,
                               UTType.utf8PlainText.identifier, UTType.plainText.identifier]

    public static func read(_ providers: [NSItemProvider]) async -> DropBatch {
        var batch = DropBatch()
        var seen = Set<String>()
        for provider in providers {
            // Browser URL titles and Cocoa's automatic text-to-URL conversion
            // both exist. Try alternate representations if one has no usable source.
            let preferred = [UTType.fileURL.identifier, UTType.url.identifier,
                             UTType.utf8PlainText.identifier, UTType.plainText.identifier]
            var resolved = false
            var failure = ["不支持这种拖放内容，请使用链接或 .torrent 文件。"]
            for type in preferred where provider.hasItemConformingToTypeIdentifier(type) {
                do {
                    let text = try await loadText(provider, type: type)
                    var parsed = DropBatch()
                    for line in text.components(separatedBy: .newlines) where !line.trimmingCharacters(in: .whitespaces).isEmpty {
                        do { parsed.sources.append(try normalize(line)) }
                        catch { parsed.errors.append(error.localizedDescription) }
                    }
                    if !parsed.sources.isEmpty {
                        for source in parsed.sources where seen.insert(source).inserted { batch.sources.append(source) }
                        batch.errors += parsed.errors
                        resolved = true
                        break
                    }
                    failure = parsed.errors.isEmpty ? ["没有找到可添加的链接或种子文件。"] : parsed.errors
                } catch { failure = [error.localizedDescription] }
            }
            if !resolved { batch.errors += failure }
        }
        if batch.sources.isEmpty && batch.errors.isEmpty { batch.errors = ["没有找到可添加的链接或种子文件。"] }
        return batch
    }

    private static func loadText(_ provider: NSItemProvider, type: String) async throws -> String {
        let item: NSSecureCoding = try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: type, options: nil) { value, error in
                if let error { continuation.resume(throwing: error) }
                else if let value { continuation.resume(returning: value) }
                else { continuation.resume(throwing: BridgeFailure.message("无法读取拖放内容。")) }
            }
        }
        let text: String
        if let url = item as? URL { text = url.absoluteString }
        else if let value = item as? String { text = value }
        else if let data = item as? Data, let value = String(data: data, encoding: .utf8) { text = value }
        else { throw BridgeFailure.message("无法识别拖放内容的格式。") }
        guard text.utf8.count <= 65536 else {
            throw BridgeFailure.message("拖入的链接文本过长，请分批添加。")
        }
        return text
    }

    public static func normalize(_ raw: String) throws -> String {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("file://"), let url = URL(string: text), url.isFileURL {
            text = url.path
        }
        if text.hasPrefix("/") || text.hasPrefix("~/") {
            let path = (text as NSString).expandingTildeInPath
            let url = URL(fileURLWithPath: path).standardizedFileURL
            guard url.pathExtension.lowercased() == "torrent" else {
                throw BridgeFailure.message("仅支持拖入 .torrent 文件：" + url.lastPathComponent)
            }
            guard (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true else {
                throw BridgeFailure.message("无法读取种子文件：" + url.lastPathComponent)
            }
            return url.path
        }
        // NSURL sometimes percent-encodes ed2k's structural pipes. Decode only
        // the separators; keep the filename capture (and its escapes) intact.
        let pattern = #"(?i)^ed2k://%7cfile%7c(.+)%7c([0-9]+)%7c([a-f0-9]{32})%7c(.*)$"#
        if let regex = try? NSRegularExpression(pattern: pattern),
           let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) {
            let groups = (1...4).map { String(text[Range(match.range(at: $0), in: text)!]) }
            let tail = groups[3].replacingOccurrences(of: "%7c", with: "|", options: .caseInsensitive)
            text = "ed2k://|file|\(groups[0])|\(groups[1])|\(groups[2])|\(tail)"
        }
        let lower = text.lowercased()
        guard lower.hasPrefix("ed2k://|file|") || lower.hasPrefix("magnet:?") else {
            throw BridgeFailure.message("仅支持 ed2k、磁力链接或本地 .torrent 文件。")
        }
        return text
    }
}
