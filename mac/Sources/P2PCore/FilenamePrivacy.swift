import Foundation

/// Presentation-only redaction: task identifiers and actual filesystem names stay intact.
public struct FilenamePrivacy {
    private var knownValues: Set<String> = []
    private var expression: NSRegularExpression?
    public init() {}

    public mutating func remember(_ tasks: [DownloadTask]) {
        let previousCount = knownValues.count
        for task in tasks {
            // Unresolved magnet metadata exposes a destination directory, not
            // a payload path. Do not treat names such as "Downloads" as files.
            var values = [task.name]
            if task.size > 0 && !task.path.isEmpty {
                values += [task.path, URL(fileURLWithPath: task.path).lastPathComponent]
            }
            for value in values where !value.isEmpty {
                knownValues.insert(value)
                if let encoded = value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) {
                    knownValues.insert(encoded)
                }
            }
        }
        if knownValues.count != previousCount {
            let pattern = knownValues.sorted { $0.count > $1.count }
                .map(NSRegularExpression.escapedPattern(for:)).joined(separator: "|")
            expression = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive)
        }
    }

    public func title(for task: DownloadTask, hidden: Bool, l: L10n) -> String {
        hidden ? l.format("下载任务 %@", String(task.id.suffix(8)).uppercased()) : task.name
    }

    public func redact(_ text: String, hidden: Bool, replacement: String) -> String {
        guard hidden, let expression else { return text }
        // A single pass avoids matching filenames inside the replacement itself.
        return expression.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text),
            withTemplate: NSRegularExpression.escapedTemplate(for: replacement))
    }
}
