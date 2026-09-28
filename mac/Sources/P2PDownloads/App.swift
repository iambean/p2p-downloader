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
        NSApp.appearance = NSAppearance(named: .darkAqua)
        NSApp.setActivationPolicy(.regular)
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "arrow.down.circle", accessibilityDescription: "Mora")
        item.button?.image?.isTemplate = true
        item.button?.target = self
        item.button?.action = #selector(toggle)
        item.button?.toolTip = "Mora"
        statusItem = item
        let previewDelete = model.demo && CommandLine.arguments.contains("--preview-delete")
        let content = previewDelete
            ? AnyView(DeleteTaskSheet(item: model.tasks[1], model: model))
            : AnyView(PanelView(model: model))
        let host = NSHostingView(rootView: content)
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 640),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        panel.title = "Mora"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.contentMinSize = NSSize(width: 720, height: 560)
        panel.appearance = NSAppearance(named: .darkAqua)
        if !model.demo { panel.setFrameAutosaveName("MoraEditorialWindow") }
        panel.contentView = host
        panel.delegate = self
        panel.isReleasedWhenClosed = false
        panel.backgroundColor = NSColor(srgbRed: 0.141, green: 0.125, blue: 0.153, alpha: 1)
        panel.hasShadow = true
        panel.level = .normal
        panel.collectionBehavior = [.moveToActiveSpace]
        panel.hidesOnDeactivate = false
        self.panel = panel
        self.host = host
        if model.demo || !panel.setFrameUsingName("MoraEditorialWindow") { panel.center() }
        model.start()
        if let index = CommandLine.arguments.firstIndex(of: "--render-preview"), CommandLine.arguments.count > index + 1 {
            let output = CommandLine.arguments[index + 1]
            panel.appearance = NSAppearance(named: .darkAqua)
            if CommandLine.arguments.contains("--preview-compact") { panel.setContentSize(NSSize(width: 720, height: 560)) }
            if previewDelete { panel.contentMinSize = NSSize(width: 1, height: 1); panel.setContentSize(host.fittingSize) }
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
        // AppKit can interpret separate CLI option values as files to open.
        // Exclude only our explicit preview/language arguments, never user drops.
        let arguments = CommandLine.arguments
        let optionPaths = ["--language", "--render-preview"].compactMap { option -> String? in
            guard let index = arguments.firstIndex(of: option), arguments.count > index + 1 else { return nil }
            return URL(fileURLWithPath: arguments[index + 1]).standardizedFileURL.path
        }
        let requested = filenames.filter { !optionPaths.contains(URL(fileURLWithPath: $0).standardizedFileURL.path) }
        guard !requested.isEmpty else { sender.reply(toOpenOrPrint: .success); return }
        showPanel()
        let providers = requested.map { NSItemProvider(object: URL(fileURLWithPath: $0) as NSURL) }
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
