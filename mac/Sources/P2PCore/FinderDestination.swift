import Foundation

public struct FinderDestination {
    public let url: URL
    public let selectFile: Bool

    public static func resolve(path: String) -> FinderDestination? {
        guard path.hasPrefix("/") else { return nil }
        var url = URL(fileURLWithPath: path).standardizedFileURL
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) {
            return FinderDestination(url: url, selectFile: !isDirectory.boolValue)
        }
        // Payload subfolders may not exist until the first piece arrives.
        // Never fall back to /Volumes or / when an external drive is missing.
        while url.pathComponents.count > 2 {
            url.deleteLastPathComponent()
            guard url.path != "/Volumes", url.path != "/Users" else { return nil }
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue {
                return FinderDestination(url: url, selectFile: false)
            }
        }
        return nil
    }
}
