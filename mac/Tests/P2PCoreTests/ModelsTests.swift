import XCTest
@testable import P2PCore

final class ModelsTests: XCTestCase {
    func testDemoUsesSameWireFormatAsBridge() throws {
        let reply = BridgeReply.demo
        XCTAssertEqual(reply.tasks?.count, 3)
        XCTAssertEqual(reply.engines?.count, 2)
        let waiting = try XCTUnwrap(reply.tasks?[1])
        XCTAssertEqual(waiting.statusTitle, "等待来源")
        XCTAssertFalse(waiting.isFinished)
        XCTAssertEqual(waiting.progressTitle, "12.5%")
    }

    func testFiltersKeepWaitingTasksActiveAndCompletionSeparate() {
        let tasks = BridgeReply.demo.tasks!
        XCTAssertEqual(tasks.filter(TaskFilter.active.matches).count, 2)
        XCTAssertEqual(tasks.filter(TaskFilter.complete.matches).count, 1)
        XCTAssertTrue(tasks.last!.isFinished)
        XCTAssertFalse(tasks.last!.canControl)
    }

    func testDeletionDefaultsToRetainingFilesForEveryBackend() {
        let tasks = BridgeReply.demo.tasks!
        let options = RemovalOptions()
        XCTAssertFalse(options.deleteFiles)
        for task in tasks {
            XCTAssertEqual(options.payload(for: task)["delete_files"], "false")
            XCTAssertTrue(task.deletionMessage(deleteFiles: false).contains("保留"))
        }
        var checked = RemovalOptions()
        checked.deleteFiles = true
        XCTAssertEqual(checked.payload(for: tasks[1])["delete_files"], "true")
        XCTAssertTrue(tasks[1].deletionMessage(deleteFiles: true).contains("废纸篓"))
        XCTAssertFalse(RemovalOptions().deleteFiles)
    }

    func testErrorResponseCanDecodeWithoutTaskData() throws {
        let reply = try JSONDecoder().decode(BridgeReply.self, from: Data(#"{"error":"Engine unavailable"}"#.utf8))
        XCTAssertEqual(reply.error, "Engine unavailable")
        XCTAssertNil(reply.tasks)
    }

    func testBackendIsPartOfTaskIdentity() throws {
        let first = BridgeReply.demo.tasks!.first!
        XCTAssertTrue(first.key.hasPrefix("bt:"))
        XCTAssertEqual(first.fraction, 0.648, accuracy: 0.00001)
    }

    func testNativeClientTalksToPythonBridgeWithoutStartingEngines() async throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let state = FileManager.default.temporaryDirectory.appendingPathComponent("p2p-native-test-" + UUID().uuidString)
        let client = BridgeClient(script: root.appendingPathComponent("gui_bridge.py"), stateDirectory: state.path)
        let reply = try await client.request(["action": "snapshot"])
        XCTAssertEqual(reply.tasks?.count, 0)
        XCTAssertEqual(reply.engines?.count, 2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: state.path))
    }
}
