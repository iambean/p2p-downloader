import AppKit
import SwiftUI
import P2PCore

enum MoraStyle {
    static let ink = Color(red: 0.141, green: 0.125, blue: 0.153)
    static let paper = Color(red: 0.965, green: 0.935, blue: 0.898)
    static let coral = Color(red: 0.88, green: 0.56, blue: 0.53)
    static let island = Color(red: 0.19, green: 0.17, blue: 0.20)
    static let muted = Color(red: 0.70, green: 0.67, blue: 0.71)
    static let rule = paper.opacity(0.13)
    // Decoded once and reused across snapshots; decoration never intercepts input.
    static let stillLife: NSImage? = Bundle.main.resourceURL
        .flatMap { NSImage(contentsOf: $0.appendingPathComponent("Artwork/WineStillLife.png")) }
}

private struct MoraButtonStyle: ButtonStyle {
    var prominent = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .padding(.horizontal, 18).padding(.vertical, 10)
            .foregroundStyle(prominent ? MoraStyle.ink : MoraStyle.paper)
            .background(prominent ? MoraStyle.coral : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(prominent ? Color.clear : MoraStyle.rule))
            .opacity(enabled ? (configuration.isPressed ? 0.75 : 1) : 0.4)
    }
}

struct PanelView: View {
    @ObservedObject var model: AppModel
    @State private var dropTargeted = false
    @FocusState private var linkFocused: Bool
    private var l: L10n { model.l }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if model.showAdd { addForm } else { entryBar }
                    if model.isBusy {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(l.text(model.busyMessage)).font(.system(size: 12))
                        }.foregroundStyle(MoraStyle.muted)
                    }
                    if let error = model.error {
                        notice(error, symbol: "exclamationmark.triangle", color: MoraStyle.coral) { model.error = nil }
                    } else if let feedback = model.feedback {
                        notice(feedback, symbol: "checkmark.circle", color: MoraStyle.paper) { model.feedback = nil }
                        if let path = model.retainedFilesPath {
                            Button { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } label: {
                                Label(l.text("查看保留的文件"), systemImage: "folder")
                            }.buttonStyle(.plain).font(.system(size: 12))
                        }
                    }
                    filters
                    if model.filteredTasks.isEmpty { emptyState }
                    else {
                        LazyVStack(spacing: 0) {
                            ForEach(model.filteredTasks, id: \.key) { item in
                                TaskRow(item: item, displayName: model.visibleName(item), detail: model.visibleText(item.detail), l: l, busy: model.isBusy, control: {
                                    model.perform(["action": item.status == "paused" ? "resume" : "pause", "id": item.id, "backend": item.backend])
                                }, reveal: { model.reveal(item) }, remove: { model.pendingDeletion = item })
                            }
                        }
                    }
                }.padding(.horizontal, 36).padding(.bottom, 22)
            }
            footer
        }
        .padding(.top, 16)
        .frame(minWidth: 720, minHeight: 560)
        .background(MoraStyle.ink.ignoresSafeArea())
        .foregroundStyle(MoraStyle.paper)
        .tint(MoraStyle.coral)
        .preferredColorScheme(.dark)
        .sheet(item: $model.pendingDeletion) { item in DeleteTaskSheet(item: item, model: model) }
        .onAppear {
            if model.demo && CommandLine.arguments.contains("--preview-drop") { dropTargeted = true }
        }
        .onDrop(of: DropSources.types, isTargeted: $dropTargeted) { model.acceptDrop($0) }
        .overlay(alignment: .top) {
            if dropTargeted {
                ZStack {
                    MoraStyle.ink.opacity(0.97)
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(MoraStyle.coral, style: StrokeStyle(lineWidth: 2, dash: [7, 5])).padding(18)
                    VStack(spacing: 8) {
                        Image(systemName: "arrow.down").font(.system(size: 24, weight: .light)).foregroundStyle(MoraStyle.coral)
                        Text(l.text(model.isBusy ? "请等待当前操作完成" : "松开以添加下载"))
                            .font(.system(size: 17, weight: .medium))
                        Text(l.text("ed2k · 磁力链接 · .torrent 文件")).font(.system(size: 13))
                        Text(l.text("支持一次拖入多个项目")).font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
                    }
                }.frame(height: 150).padding(.horizontal, 22).padding(.top, 202).allowsHitTesting(false)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 24) {
            VStack(alignment: .leading, spacing: 0) {
                Text("Mora").font(.custom("Baskerville-Italic", size: 82)).tracking(-2)
                    .accessibilityAddTraits(.isHeader)
                Text(l.text(model.demo ? "界面预览 · 示例任务" : "为下一份期待，留一点空间。"))
                    .font(.system(size: 14)).foregroundStyle(MoraStyle.muted)
            }
            Spacer(minLength: 0)
            if let art = MoraStyle.stillLife {
                Image(nsImage: art).resizable().scaledToFit()
                    .frame(width: 270, height: 180)
                    .accessibilityHidden(true).allowsHitTesting(false)
            }
        }.padding(.horizontal, 36).padding(.top, 0).padding(.bottom, 14)
    }

    private var entryBar: some View {
        HStack(spacing: 20) {
            HStack(spacing: 12) {
                Image(systemName: "link").font(.system(size: 17, weight: .light)).foregroundStyle(MoraStyle.muted)
                TextField(l.text("粘贴链接，或拖入种子文件"), text: $model.link)
                    .textFieldStyle(.plain).font(.system(size: 13)).focused($linkFocused)
                    .accessibilityLabel(l.text("下载链接")).onSubmit { model.addLink() }
                Button(l.text("添加")) {
                    if model.link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        model.showAdd = true; linkFocused = true
                    } else { model.addLink() }
                }.buttonStyle(MoraButtonStyle(prominent: true)).disabled(model.isBusy)
            }.padding(.leading, 14).padding(1)
                .overlay(RoundedRectangle(cornerRadius: 9).stroke(linkFocused ? MoraStyle.coral.opacity(0.65) : MoraStyle.rule))
            Button(l.text("导入种子…")) { model.importTorrent() }
                .buttonStyle(.plain).font(.system(size: 12)).fixedSize().disabled(model.isBusy)
        }
        .background {
            Button("") { model.showAdd = true; linkFocused = true }
                .keyboardShortcut("n", modifiers: .command).hidden().accessibilityHidden(true)
        }.disabled(model.isBusy)
    }

    private var filters: some View {
        HStack(spacing: 26) {
            ForEach(TaskFilter.allCases, id: \.self) { filter in
                Button { model.filter = filter } label: {
                    HStack(spacing: 6) {
                        Text(l.text(filter.rawValue))
                        Text("\(model.tasks.filter(filter.matches).count)").font(.system(size: 11)).foregroundStyle(MoraStyle.muted)
                    }.font(.system(size: 13))
                        .foregroundStyle(model.filter == filter ? MoraStyle.paper : MoraStyle.muted)
                        .padding(.horizontal, 4).padding(.vertical, 14)
                        .overlay(alignment: .bottom) {
                            if model.filter == filter { MoraStyle.coral.frame(height: 2) }
                        }
                }.buttonStyle(.plain)
                    .accessibilityAddTraits(model.filter == filter ? [.isSelected] : [])
            }
            Spacer(minLength: 0)
            Button { model.hidesFileNames.toggle() } label: {
                Image(systemName: model.hidesFileNames ? "eye.slash" : "eye")
                    .font(.system(size: 14)).frame(width: 30, height: 30)
                    .foregroundStyle(model.hidesFileNames ? MoraStyle.coral : MoraStyle.muted)
            }.buttonStyle(.plain)
                .help(l.text(model.hidesFileNames ? "显示文件名" : "隐藏文件名"))
                .accessibilityLabel(l.text(model.hidesFileNames ? "显示文件名" : "隐藏文件名"))
                .accessibilityValue(l.text(model.hidesFileNames ? "文件名已隐藏" : "文件名已显示"))
            if model.isRefreshing { ProgressView().controlSize(.mini) }
        }.overlay(alignment: .bottom) { MoraStyle.rule.frame(height: 1) }
            .accessibilityElement(children: .contain).accessibilityLabel(l.text("任务分类"))
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(l.text("添加下载")).font(.system(size: 18, weight: .medium, design: .serif))
            TextField(l.text("粘贴 ed2k 或磁力链接，无需引号"), text: $model.link, axis: .vertical)
                .textFieldStyle(.plain).font(.system(size: 13)).lineLimit(2...3)
                .padding(12).overlay(RoundedRectangle(cornerRadius: 7).stroke(MoraStyle.rule))
                .focused($linkFocused).onSubmit { model.addLink() }.accessibilityLabel(l.text("下载链接"))
            HStack(spacing: 12) {
                Image(systemName: "folder").foregroundStyle(MoraStyle.muted)
                Text(model.output.isEmpty ? l.text("默认下载目录") : model.visibleText(model.output))
                    .lineLimit(1).truncationMode(.middle).font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
                    .help(model.output.isEmpty ? l.text("首次下载使用 ~/Downloads/P2P，已有 ed2k 实例沿用原目录") : model.visibleText(model.output))
                Spacer(minLength: 0)
                Button(l.text("选择下载目录…")) { model.chooseDirectory() }.buttonStyle(.plain).font(.system(size: 12))
            }.padding(12).overlay(RoundedRectangle(cornerRadius: 7).stroke(MoraStyle.rule))
            HStack {
                Button(l.text("导入种子…")) { model.importTorrent() }.buttonStyle(.plain).font(.system(size: 12))
                Spacer()
                Button(l.text("取消")) { model.showAdd = false }.buttonStyle(MoraButtonStyle())
                Button(l.text("添加任务")) { model.addLink() }.buttonStyle(MoraButtonStyle(prominent: true))
                    .disabled(model.link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(20).background(MoraStyle.island.opacity(0.30), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(MoraStyle.rule))
            .disabled(model.isBusy)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "tray").font(.system(size: 30, weight: .ultraLight)).foregroundStyle(MoraStyle.muted)
            Text(l.text(model.filter == .all ? "为下一份期待，留一点空间。" : "这里还没有任务"))
                .font(.system(size: 20, weight: .regular, design: .serif))
            Text(l.text("在上方粘贴链接，或将种子文件拖到这里。"))
                .font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
            if !model.showAdd {
                Button(l.text("添加第一个任务")) { model.showAdd = true; linkFocused = true }
                    .buttonStyle(MoraButtonStyle()).foregroundStyle(MoraStyle.coral)
            }
        }.frame(maxWidth: .infinity).padding(.vertical, 38)
    }

    private func notice(_ text: String, symbol: String, color: Color, dismiss: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(l.text(model.visibleText(text))).font(.system(size: 12)).textSelection(.enabled).lineLimit(7)
            Spacer(minLength: 0)
            Button(action: dismiss) { Image(systemName: "xmark") }.buttonStyle(.plain).help(l.text("关闭提示"))
        }.padding(12).background(color.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
    }

    private var footer: some View {
        VStack(spacing: 8) {
            Rectangle().fill(MoraStyle.muted.opacity(0.18)).frame(height: 1)
            HStack(spacing: 12) {
                ForEach(model.snapshot.engines ?? []) { engine in
                    Menu {
                        Text(l.text(engine.explanation))
                        Text(l.text(model.visibleText(engine.detail)))
                        if let error = engine.error { Button(l.text("查看错误详情")) { model.error = error } }
                        if engine.available && !engine.running {
                            Button(l.format("启动 %@", engine.name)) { model.perform(["action": "start", "backend": engine.id]) }
                        }
                        if engine.running {
                            Text(l.text("停止会保存任务并中断该引擎的传输，重新启动后可继续。"))
                            Button(l.format("停止 %@", engine.name)) { model.perform(["action": "stop", "backend": engine.id]) }
                        }
                        if !engine.available { Text(l.format("请先安装 %@ 下载组件", engine.id == "ed2k" ? "aMule" : "aria2")) }
                    } label: {
                        HStack(spacing: 6) {
                            Circle().fill(engine.error != nil ? MoraStyle.coral : engine.running ? Color(red: 0.66, green: 0.79, blue: 0.65) : MoraStyle.muted)
                                .frame(width: 5, height: 5)
                            Text(engine.name + " · " + l.text(engine.title))
                        }
                    }.menuStyle(.borderlessButton).fixedSize().disabled(model.isBusy)
                        .tint(MoraStyle.muted).padding(.trailing, 10).padding(.vertical, 8)
                }
                Spacer(minLength: 4)
                Button { model.openFolder() } label: { Image(systemName: "folder") }
                    .help(l.text("文件夹")).accessibilityLabel(l.text("文件夹"))
                Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }
                    .help(l.text("刷新")).accessibilityLabel(l.text("刷新"))
                    .disabled(model.isBusy || model.isRefreshing)
                Menu {
                    Button(l.text("选择下载目录…")) { model.chooseDirectory() }
                    Button(l.text("恢复默认目录")) { model.output = ""; UserDefaults.standard.removeObject(forKey: "outputDirectory") }
                    Divider()
                    Toggle(l.text("隐藏文件名"), isOn: $model.hidesFileNames)
                    Divider()
                    Picker(l.text("语言"), selection: Binding(get: { model.language }, set: model.setLanguage)) {
                        Text(l.text("跟随系统")).tag(AppLanguage.system)
                        Text("简体中文").tag(AppLanguage.chinese)
                        Text("English").tag(AppLanguage.english)
                    }
                    Text(l.text("系统对话框将在下次启动时使用所选语言。"))
                    Divider()
                    UpdateMenuItems(updater: model.updater, l: l)
                    Divider()
                    Text(l.text("隐藏后每分钟刷新，下载继续在后台运行。"))
                    Text(l.text("退出界面不会停止下载引擎。"))
                    Button(l.text("退出")) { NSApp.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "gearshape") }
                    .menuStyle(.borderlessButton).fixedSize().help(l.text("设置")).accessibilityLabel(l.text("设置"))
            }.buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
        }.padding(.horizontal, 36).padding(.bottom, 18)
    }
}

struct DeleteTaskSheet: View {
    let item: DownloadTask
    @ObservedObject var model: AppModel
    private var l: L10n { model.l }
    @State private var options = RemovalOptions()
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(l.text("删除这个任务？"), systemImage: "trash").font(.system(size: 19, weight: .medium))
            Text(model.visibleName(item)).font(.system(size: 13)).foregroundStyle(MoraStyle.muted).lineLimit(3)
            Toggle(l.text("同时删除已下载的文件"), isOn: $options.deleteFiles).toggleStyle(.checkbox).font(.system(size: 13))
            Text(l.text(item.deletionMessage(deleteFiles: options.deleteFiles)))
                .font(.system(size: 12)).foregroundStyle(MoraStyle.muted).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(l.text("取消")) { model.pendingDeletion = nil }.buttonStyle(MoraButtonStyle()).keyboardShortcut(.cancelAction)
                Button(l.text(options.deleteFiles ? "删除任务和文件" : "仅删除任务"), role: .destructive) {
                    let choice = options
                    model.pendingDeletion = nil
                    model.remove(item, options: choice)
                }.buttonStyle(MoraButtonStyle(prominent: true)).keyboardShortcut(.defaultAction).disabled(model.isBusy)
            }
        }.padding(28).frame(width: 410).foregroundStyle(MoraStyle.paper)
            .background(MoraStyle.ink).tint(MoraStyle.coral).preferredColorScheme(.dark)
            .onAppear {
                options = RemovalOptions()
                if model.demo && CommandLine.arguments.contains("--preview-delete-files") { options.deleteFiles = true }
            }
    }
}

private struct TaskRow: View {
    let item: DownloadTask
    let displayName: String
    let detail: String
    let l: L10n
    let busy: Bool
    let control: () -> Void
    let reveal: () -> Void
    let remove: () -> Void
    var body: some View {
        GeometryReader { geometry in
            HStack(spacing: 18) {
                Image(systemName: "doc").font(.system(size: 24, weight: .ultraLight))
                    .frame(width: 28).foregroundStyle(MoraStyle.paper).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text(displayName).font(.system(size: 14, weight: .medium)).lineLimit(2).help(displayName)
                    Text(metadata).font(.system(size: 11)).foregroundStyle(MoraStyle.muted).lineLimit(2).help(metadata)
                }.frame(width: max(180, geometry.size.width * 0.36), alignment: .leading)
                HStack(spacing: 14) {
                    GeometryReader { bar in
                        Capsule().fill(MoraStyle.paper.opacity(0.12))
                            .overlay(alignment: .leading) {
                                Capsule().fill(item.status == "paused" ? MoraStyle.coral.opacity(0.65) : MoraStyle.coral)
                                    .frame(width: bar.size.width * item.fraction)
                            }
                    }.frame(height: 5).accessibilityLabel(l.text("下载进度")).accessibilityValue(item.progressTitle)
                    Text(item.progressTitle).font(.system(size: 11)).monospacedDigit().foregroundStyle(MoraStyle.muted).frame(width: 46, alignment: .trailing)
                }.frame(maxWidth: .infinity)
                HStack(spacing: 14) {
                    if item.isFinished {
                        rowButton("folder", title: "在 Finder 中显示", action: reveal)
                    } else if item.canControl {
                        rowButton(item.status == "paused" ? "play.fill" : "pause.fill", title: item.status == "paused" ? "恢复" : "暂停", action: control).disabled(busy)
                    } else {
                        Image(systemName: item.status == "error" ? "exclamationmark.triangle" : "clock")
                            .foregroundStyle(MoraStyle.coral).frame(width: 32, height: 32)
                    }
                    Menu { taskActions } label: { Image(systemName: "ellipsis").frame(width: 22, height: 32) }
                        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().tint(MoraStyle.paper)
                        .help(l.text("任务操作")).accessibilityLabel(l.text("任务操作"))
                }.frame(width: 78)
            }.frame(maxHeight: .infinity)
        }.frame(height: 90).foregroundStyle(MoraStyle.paper)
            .contentShape(Rectangle()).contextMenu { taskActions }
            .overlay(alignment: .bottom) { MoraStyle.rule.frame(height: 1) }
    }

    private var metadata: String {
        var parts = [item.backend == "ed2k" ? "ED2K" : "BT", l.text(item.sizeTitle), l.text(item.statusTitle)]
        if !item.speed.isEmpty { parts.append(item.speed) }
        else if !item.sources.isEmpty && !item.isFinished { parts.append(l.format("来源 %@", item.sources)) }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private var taskActions: some View {
        Button(action: reveal) { Label(l.text("在 Finder 中显示"), systemImage: "folder") }
        Divider()
        Button(l.text("复制文件名")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.name, forType: .string) }
        Button(l.text("复制任务 ID")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.id, forType: .string) }
        Divider()
        Button(role: .destructive, action: remove) { Label(l.text("删除任务…"), systemImage: "trash") }.disabled(busy)
        if !detail.isEmpty { Text(l.text(detail)) }
    }

    private func rowButton(_ symbol: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).font(.system(size: 12)).frame(width: 32, height: 32) }
            .buttonStyle(.plain).foregroundStyle(item.status == "paused" ? MoraStyle.muted : MoraStyle.coral)
            .overlay(Circle().stroke(item.status == "paused" ? MoraStyle.muted.opacity(0.7) : MoraStyle.coral, lineWidth: 1))
            .help(l.text(title)).accessibilityLabel(l.text(title))
    }
}
