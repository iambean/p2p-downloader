import AppKit
import SwiftUI

@main
struct P2PDownloadsApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene { Settings { EmptyView() } }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let model = AppModel()
    private var statusItem: NSStatusItem?
    private var panel: NSWindow?
    private var host: NSHostingView<AnyView>?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "arrow.down.circle", accessibilityDescription: "P2P 下载")
        item.button?.image?.isTemplate = true
        item.button?.target = self
        item.button?.action = #selector(toggle)
        item.button?.toolTip = "P2P 下载"
        statusItem = item
        let previewDelete = model.demo && CommandLine.arguments.contains("--preview-delete")
        let content = previewDelete
            ? AnyView(DeleteTaskSheet(item: model.tasks[1], model: model))
            : AnyView(PanelView(model: model))
        let host = NSHostingView(rootView: content)
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 660),
                             styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        panel.title = "P2P 下载"
        panel.setFrameAutosaveName("P2PDownloadsMainWindow")
        panel.contentView = host
        panel.delegate = self
        panel.isReleasedWhenClosed = false
        panel.backgroundColor = .windowBackgroundColor
        panel.hasShadow = true
        panel.level = .normal
        panel.collectionBehavior = [.moveToActiveSpace]
        panel.hidesOnDeactivate = false
        self.panel = panel
        self.host = host
        if !panel.setFrameUsingName("P2PDownloadsMainWindow") { panel.center() }
        model.start()
        if let index = CommandLine.arguments.firstIndex(of: "--render-preview"), CommandLine.arguments.count > index + 1 {
            let output = CommandLine.arguments[index + 1]
            panel.appearance = NSAppearance(named: .aqua)
            if previewDelete { panel.setContentSize(host.fittingSize) }
            panel.center()
            panel.makeKeyAndOrderFront(nil)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                self?.renderPreview(to: output)
            }
        } else {
            showPanel()
        }
    }

    @objc private func toggle() {
        if panel?.isVisible == true { panel?.orderOut(nil); model.panelVisible = false }
        else { showPanel() }
    }

    private func showPanel() {
        guard let panel else { return }
        if panel.isMiniaturized { panel.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        model.panelVisible = true
        model.refresh()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showPanel()
        return true
    }

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        showPanel()
        let providers = filenames.map { NSItemProvider(object: URL(fileURLWithPath: $0) as NSURL) }
        sender.reply(toOpenOrPrint: model.acceptDrop(providers) ? .success : .failure)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func windowWillClose(_ notification: Notification) { model.panelVisible = false }
    func windowDidMiniaturize(_ notification: Notification) { model.panelVisible = false }
    func windowDidDeminiaturize(_ notification: Notification) { model.panelVisible = true; model.refresh() }

    private func renderPreview(to path: String) {
        guard let host else { NSApp.terminate(nil); return }
        host.layoutSubtreeIfNeeded()
        host.displayIfNeeded()
        if let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
            host.cacheDisplay(in: host.bounds, to: bitmap)
            if let png = bitmap.representation(using: .png, properties: [:]) {
                try? png.write(to: URL(fileURLWithPath: path))
            }
        }
        NSApp.terminate(nil)
    }
}
