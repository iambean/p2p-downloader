import XCTest
@testable import P2PCore

final class PresentationTests: XCTestCase {
    func testEnglishDefaultAndSystemDialogPreference() throws {
        let suite = "Mora.LanguageTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertEqual(AppLanguage.stored(nil), .english)
        XCTAssertEqual(AppLanguage.stored("invalid"), .english)
        AppLanguage.prepareSystemDialogs(defaults: defaults)
        XCTAssertEqual(defaults.stringArray(forKey: "AppleLanguages"), ["en"])
        defaults.set("zh-Hans", forKey: "appLanguage")
        AppLanguage.prepareSystemDialogs(defaults: defaults)
        XCTAssertEqual(defaults.stringArray(forKey: "AppleLanguages"), ["zh-Hans"])
        defaults.set("system", forKey: "appLanguage")
        AppLanguage.prepareSystemDialogs(defaults: defaults)
        XCTAssertNil(defaults.persistentDomain(forName: suite)?["AppleLanguages"])
        XCTAssertEqual(AppLanguage.stored(defaults.string(forKey: "appLanguage")), .system)
    }

    func testEnglishDownloadAndErrorMessages() {
        let l = L10n(.english)
        XCTAssertEqual(l.text("下载并发"), "Parallel downloads")
        XCTAssertEqual(l.text("1 个连接"), "1 connection")
        XCTAssertEqual(l.format("%d 个连接", 4), "4 connections")
        XCTAssertEqual(l.text("无法读取控制接口错误详情：HTTP 400"), "Cannot read the control response error details: HTTP 400")
        XCTAssertEqual(l.text("下载目录所在磁盘发生变化，未删除文件。"), "The download drive has changed. No files were deleted.")
        XCTAssertEqual(l.text("无法读取种子文件：/tmp/中文.torrent"), "Cannot read torrent file: /tmp/中文.torrent")
    }

    func testLanguageSelectionAndFormattedMessages() {
        XCTAssertEqual(AppLanguage.system.resolved(preferred: ["zh-Hans-CN"]), .chinese)
        XCTAssertEqual(AppLanguage.system.resolved(preferred: ["fr-FR", "zh-Hans"]), .english)
        XCTAssertEqual(AppLanguage.english.resolved(preferred: ["zh-Hans"]), .english)
        XCTAssertEqual(L10n(.english).text("在 Finder 中显示"), "Show in Finder")
        XCTAssertEqual(L10n(.chinese).text("在 Finder 中显示"), "在 Finder 中显示")
        XCTAssertEqual(L10n(.english).format("启动 %@", "eD2k"), "Start eD2k")
        XCTAssertEqual(L10n(.english).format("第 %d 项：%@", 2, "fixture.torrent"), "Item 2: fixture.torrent")
        XCTAssertEqual(L10n(.english).text("无法读取种子文件：/tmp/中文.torrent"), "Cannot read torrent file: /tmp/中文.torrent")
        XCTAssertEqual(L10n(.english).text("中文文件.zip"), "中文文件.zip")
    }

    func testFinderSelectsPartialFilesAndOpensFoldersWithoutExecutingFiles() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let partial = root.appendingPathComponent("001.part")
        try Data("partial".utf8).write(to: partial)
        XCTAssertTrue(try XCTUnwrap(FinderDestination.resolve(path: partial.path)).selectFile)
        XCTAssertFalse(try XCTUnwrap(FinderDestination.resolve(path: root.path)).selectFile)
        let pending = try XCTUnwrap(FinderDestination.resolve(path: root.appendingPathComponent("pending/subfolder/file.iso").path))
        XCTAssertFalse(pending.selectFile)
        XCTAssertEqual(pending.url, root.standardizedFileURL)
        XCTAssertNil(FinderDestination.resolve(path: ""))
        XCTAssertNil(FinderDestination.resolve(path: "/Volumes/absent-" + UUID().uuidString + "/file.iso"))
    }

    func testEngineLabelsSeparateStoppedRunningAndControlFailure() throws {
        func engine(_ running: Bool, _ error: String? = nil) throws -> EngineState {
            var raw: [String: Any] = ["id": "bt", "name": "BitTorrent", "available": true, "running": running, "detail": "Ready"]
            raw["error"] = error
            return try JSONDecoder().decode(EngineState.self, from: JSONSerialization.data(withJSONObject: raw))
        }
        XCTAssertEqual(try engine(false).title, "未启动")
        XCTAssertEqual(try engine(true).title, "运行中")
        XCTAssertEqual(try engine(false, "Authentication failed").title, "未就绪")
    }
}
