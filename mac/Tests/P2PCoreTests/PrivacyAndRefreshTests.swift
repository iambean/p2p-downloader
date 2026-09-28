import XCTest
@testable import P2PCore

final class PrivacyAndRefreshTests: XCTestCase {
    private func task(_ name: String = "私人文件.zip", path: String = "") -> DownloadTask {
        DownloadTask(id: "01234567abcdef12", name: name, backend: "bt", status: "paused", progress: 42,
                     size: 1024, speed: "", sources: "0", path: path, detail: "")
    }

    func testVisibilityChangesPresentationWithoutChangingTaskIdentityOrName() {
        let item = task()
        let privacy = FilenamePrivacy()
        XCTAssertEqual(privacy.title(for: item, hidden: false, l: L10n(.english)), item.name)
        XCTAssertEqual(privacy.title(for: item, hidden: true, l: L10n(.english)), "Download ABCDEF12")
        XCTAssertEqual(privacy.title(for: item, hidden: true, l: L10n(.chinese)), "下载任务 ABCDEF12")
        XCTAssertEqual(item.name, "私人文件.zip")
        XCTAssertEqual(RemovalOptions().payload(for: item)["id"], "01234567abcdef12")
    }

    func testErrorsAndTooltipsCanRedactNamesEvenAfterTaskDisappears() {
        let item = task(path: "/tmp/private/私人文件.zip")
        var privacy = FilenamePrivacy()
        privacy.remember([item])
        privacy.remember([])
        let message = "Failed: \(item.path) / \(item.name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)!)"
        let redacted = privacy.redact(message, hidden: true, replacement: "[hidden]")
        XCTAssertEqual(redacted, "Failed: [hidden] / [hidden]")
        XCTAssertEqual(privacy.redact(message, hidden: false, replacement: "[hidden]"), message)
    }

    func testReplacementDoesNotGetRedactedAgainAndSpecialCharactersAreLiteral() {
        var privacy = FilenamePrivacy()
        privacy.remember([task("File", path: "/tmp/File"), task("[notes]+(1).zip")])
        XCTAssertEqual(privacy.redact("/tmp/File", hidden: true, replacement: "File name hidden"), "File name hidden")
        XCTAssertEqual(privacy.redact("Error: [notes]+(1).zip", hidden: true, replacement: "[hidden]"), "Error: [hidden]")
    }

    func testLateReadCannotUndoConfirmedPauseOrNextMutation() {
        var generation = SnapshotGeneration()
        let periodicRead = generation.current
        generation.invalidate()  // Pause begins while the old read is in flight.
        let postPauseRead = generation.current
        var displayedStatus = "active"
        if generation.accepts(postPauseRead) { displayedStatus = "paused" }
        if generation.accepts(periodicRead) { displayedStatus = "active" }
        XCTAssertEqual(displayedStatus, "paused")
        generation.invalidate()  // User resumes; even a pre-resume read is obsolete.
        XCTAssertFalse(generation.accepts(postPauseRead))
        XCTAssertTrue(generation.accepts(generation.current))
    }

    func testMetadataDirectoryDoesNotRedactGenericDownloadMessages() {
        let item = DownloadTask(id: "01234567abcdef12", name: "[METADATA]fixture", backend: "bt",
            status: "waiting", progress: 0, size: 0, speed: "", sources: "0", path: "/tmp/Downloads", detail: "")
        var privacy = FilenamePrivacy()
        privacy.remember([item])
        XCTAssertEqual(privacy.redact("Downloads are running", hidden: true, replacement: "[hidden]"), "Downloads are running")
        XCTAssertEqual(privacy.redact("Error: [METADATA]fixture", hidden: true, replacement: "[hidden]"), "Error: [hidden]")
    }
}
