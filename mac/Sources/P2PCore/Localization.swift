import Foundation

public enum AppLanguage: String, CaseIterable {
    case system, chinese = "zh-Hans", english = "en"
    public func resolved(preferred: [String] = Locale.preferredLanguages) -> AppLanguage {
        self == .system ? ((preferred.first ?? "en").hasPrefix("zh") ? .chinese : .english) : self
    }
}

public struct L10n {
    public let language: AppLanguage
    public init(_ language: AppLanguage) { self.language = language.resolved() }
    public static let catalog: [String: String] = {
        let packaged = Bundle.main.resourceURL?.appendingPathComponent("locales/en.json")
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("locales/en.json")
        for url in [packaged, source].compactMap({ $0 }) {
            if let data = try? Data(contentsOf: url), let values = try? JSONDecoder().decode([String: String].self, from: data) { return values }
        }
        return [:]
    }()
    public func text(_ key: String) -> String {
        guard language == .english else { return key }
        if let translated = Self.catalog[key] { return translated }
        // Only replace known message prefixes, not file names embedded in diagnostics.
        for prefix in Self.catalog.keys.filter({ $0.hasSuffix("：") || $0.hasSuffix("\n") || $0.hasSuffix(" ") }).sorted(by: { $0.count > $1.count }) {
            if key.hasPrefix(prefix) { return Self.catalog[prefix]! + String(key.dropFirst(prefix.count)) }
        }
        return key
    }
    public func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: Locale(identifier: language == .english ? "en_US" : "zh_CN"), arguments: arguments)
    }
}
