// Read-only Sparkle integration probe. It never downloads or installs an update.
import AppKit
import Foundation
import Sparkle

final class Probe: NSObject, SPUUpdaterDelegate {
    let feed: String
    var finished = false
    var succeeded = false
    init(feed: String) { self.feed = feed }
    func feedURLString(for updater: SPUUpdater) -> String? { feed }
    func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        print("Sparkle accepted signed feed: version=\(item.displayVersionString) build=\(item.versionString)")
        succeeded = true
        finished = true
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        fputs("Sparkle probe failed: \(error.localizedDescription)\n", stderr)
        finished = true
    }
    func updaterDidNotFindUpdate(_ updater: SPUUpdater, error: Error) {
        fputs("Expected an update, but none was found: \(error.localizedDescription)\n", stderr)
        finished = true
    }
}

guard CommandLine.arguments.count == 3,
      let host = Bundle(path: CommandLine.arguments[1]) else { exit(2) }
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = Probe(feed: CommandLine.arguments[2])
let driver = SPUStandardUserDriver(hostBundle: host, delegate: nil)
let updater = SPUUpdater(hostBundle: host, applicationBundle: host, userDriver: driver, delegate: delegate)
do { try updater.start() } catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(1)
}
updater.checkForUpdateInformation()
let deadline = Date().addingTimeInterval(30)
while !delegate.finished && Date() < deadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
}
exit(delegate.succeeded ? 0 : 1)
