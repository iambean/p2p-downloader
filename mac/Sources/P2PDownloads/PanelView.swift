import AppKit
import SwiftUI
import P2PCore

enum MoraStyle {
    static let ink = Color(red: 0.153, green: 0.129, blue: 0.173)
    static let paper = Color(red: 0.965, green: 0.935, blue: 0.898)
    static let coral = Color(red: 0.945, green: 0.631, blue: 0.533)
    static let island = Color(red: 0.302, green: 0.267, blue: 0.333)
    static let muted = Color(red: 0.760, green: 0.721, blue: 0.788)
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
                    if model.showAdd { addForm } else { dropWell }
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
                        LazyVStack(spacing: 12) {
                            ForEach(model.filteredTasks, id: \.key) { item in
                                TaskRow(item: item, l: l, busy: model.isBusy, control: {
                                    model.perform(["action": item.status == "paused" ? "resume" : "pause", "id": item.id, "backend": item.backend])
                                }, reveal: { model.reveal(item) }, remove: { model.pendingDeletion = item })
                            }
                        }
                    }
                }.padding(.horizontal, 28).padding(.bottom, 22)
            }
            footer
        }
        .padding(.top, 16)
        .frame(minWidth: 640, minHeight: 520)
        .background(MoraStyle.ink.ignoresSafeArea())
        .foregroundStyle(MoraStyle.paper)
        .tint(MoraStyle.coral)
        .preferredColorScheme(.dark)
        .sheet(item: $model.pendingDeletion) { item in DeleteTaskSheet(item: item, model: model) }
        .onDrop(of: DropSources.types, isTargeted: $dropTargeted) { model.acceptDrop($0) }
        .overlay {
            if dropTargeted {
                ZStack {
                    MoraStyle.ink.opacity(0.97)
                    RoundedRectangle(cornerRadius: 20)
                        .stroke(MoraStyle.coral, style: StrokeStyle(lineWidth: 2, dash: [7, 5])).padding(18)
                    VStack(spacing: 14) {
                        Image(systemName: "arrow.down").font(.system(size: 40, weight: .light)).foregroundStyle(MoraStyle.coral)
                        Text(l.text(model.isBusy ? "请等待当前操作完成" : "松开以添加下载"))
                            .font(.system(size: 21, weight: .medium))
                        Text(l.text("ed2k · 磁力链接 · .torrent 文件")).font(.system(size: 13))
                        Text(l.text("支持一次拖入多个项目")).font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
                    }
                }.allowsHitTesting(false)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 0) {
                Text("Mora").font(.custom("Baskerville-BoldItalic", size: 60)).tracking(-2)
                    .accessibilityAddTraits(.isHeader)
                Text(l.text(model.demo ? "界面预览 · 示例任务" : "为下一份期待，留一点空间。"))
                    .font(.system(size: 13)).foregroundStyle(MoraStyle.muted)
            }
            Spacer()
            if model.isRefreshing { ProgressView().controlSize(.small) }
            Button {
                model.showAdd.toggle()
                linkFocused = model.showAdd
            } label: {
                Label(l.text(model.showAdd ? "收起" : "添加"), systemImage: model.showAdd ? "minus" : "plus")
                    .font(.system(size: 15, weight: .medium)).padding(.horizontal, 22).padding(.vertical, 12)
                    .foregroundStyle(MoraStyle.ink).background(MoraStyle.coral, in: Capsule())
            }.buttonStyle(.plain).help(l.text("添加下载")).keyboardShortcut("n", modifiers: .command)
        }.padding(.horizontal, 28).padding(.top, 6).padding(.bottom, 20)
    }

    private var dropWell: some View {
        VStack(alignment: .trailing, spacing: 8) {
            Button { model.showAdd = true; linkFocused = true } label: {
                VStack(spacing: 6) {
                    Image(systemName: "arrow.down").font(.system(size: 18, weight: .light))
                    Text(l.text("拖入链接或种子文件")).font(.system(size: 14))
                }.foregroundStyle(MoraStyle.muted).frame(maxWidth: .infinity).frame(height: 68)
                    .contentShape(RoundedRectangle(cornerRadius: 22))
                    .overlay(RoundedRectangle(cornerRadius: 22).stroke(MoraStyle.muted.opacity(0.5), style: StrokeStyle(lineWidth: 1, dash: [3, 4])))
            }.buttonStyle(.plain).help(l.text("点击粘贴链接，也可直接拖入文件"))
            Button(l.text("导入种子…")) { model.importTorrent() }
                .font(.system(size: 11)).buttonStyle(.plain).foregroundStyle(MoraStyle.muted)
                .disabled(model.isBusy)
        }
    }

    private var filters: some View {
        HStack(spacing: 6) {
            ForEach(TaskFilter.allCases, id: \.self) { filter in
                Button { model.filter = filter } label: {
                    HStack(spacing: 5) {
                        Text(l.text(filter.rawValue))
                        Text("\(model.tasks.filter(filter.matches).count)").font(.system(size: 10)).opacity(0.65)
                    }
                    .font(.system(size: 12, weight: model.filter == filter ? .medium : .regular))
                    .padding(.horizontal, 13).padding(.vertical, 7)
                    .foregroundStyle(model.filter == filter ? MoraStyle.ink : MoraStyle.muted)
                    .background(model.filter == filter ? MoraStyle.paper : .clear, in: Capsule())
                }.buttonStyle(.plain)
                    .accessibilityAddTraits(model.filter == filter ? [.isSelected] : [])
            }
            Spacer(minLength: 0)
        }.accessibilityElement(children: .contain).accessibilityLabel(l.text("任务分类"))
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(l.text("添加下载")).font(.system(size: 13, weight: .medium))
                Spacer()
                Button(l.text("导入种子…")) { model.importTorrent() }.buttonStyle(.plain).font(.system(size: 12))
            }
            TextField(l.text("粘贴 ed2k 或磁力链接，无需引号"), text: $model.link, axis: .vertical)
                .textFieldStyle(.plain).font(.system(size: 13)).lineLimit(2...3)
                .padding(12).background(MoraStyle.ink, in: RoundedRectangle(cornerRadius: 10))
                .focused($linkFocused).onSubmit { model.addLink() }.accessibilityLabel(l.text("下载链接"))
            HStack {
                Button { model.chooseDirectory() } label: {
                    Label(model.output.isEmpty ? l.text("默认下载目录") : URL(fileURLWithPath: model.output).lastPathComponent, systemImage: "folder")
                        .lineLimit(1).truncationMode(.middle)
                }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(MoraStyle.muted)
                    .help(model.output.isEmpty ? l.text("首次下载使用 ~/Downloads/P2P，已有 ed2k 实例沿用原目录") : model.output)
                Spacer()
                Button(l.text("添加任务")) { model.addLink() }
                    .buttonStyle(.borderedProminent).controlSize(.small)
                    .disabled(model.link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(16).background(MoraStyle.island.opacity(0.6), in: RoundedRectangle(cornerRadius: 20))
            .disabled(model.isBusy)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "tray").font(.system(size: 27, weight: .ultraLight)).foregroundStyle(MoraStyle.coral)
            Text(l.text(model.filter == .all ? "暂时没有可显示的任务" : "这里还没有任务"))
                .font(.system(size: 15, weight: .medium))
            Text(l.text("拖入链接或种子文件，也可以点击按钮添加。"))
                .font(.system(size: 12)).foregroundStyle(MoraStyle.muted)
            if !model.showAdd {
                Button(l.text("添加第一个任务")) { model.showAdd = true; linkFocused = true }
                    .buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(MoraStyle.coral)
            }
        }.frame(maxWidth: .infinity).padding(.vertical, 24)
    }

    private func notice(_ text: String, symbol: String, color: Color, dismiss: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(l.text(text)).font(.system(size: 12)).textSelection(.enabled).lineLimit(7)
            Spacer(minLength: 0)
            Button(action: dismiss) { Image(systemName: "xmark") }.buttonStyle(.plain).help(l.text("关闭提示"))
        }.padding(12).background(color.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
    }

    private var footer: some View {
        VStack(spacing: 14) {
            Rectangle().fill(MoraStyle.muted.opacity(0.18)).frame(height: 1)
            HStack(spacing: 12) {
                ForEach(model.snapshot.engines ?? []) { engine in
                    Menu {
                        Text(l.text(engine.explanation))
                        Text(l.text(engine.detail))
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
                        .tint(MoraStyle.muted).padding(.horizontal, 10).padding(.vertical, 8)
                        .background(MoraStyle.island.opacity(0.55), in: RoundedRectangle(cornerRadius: 11))
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
        }.padding(.horizontal, 28).padding(.bottom, 18)
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
            Text(item.name).font(.system(size: 13)).foregroundStyle(MoraStyle.muted).lineLimit(3)
            Toggle(l.text("同时删除已下载的文件"), isOn: $options.deleteFiles).toggleStyle(.checkbox).font(.system(size: 13))
            Text(l.text(item.deletionMessage(deleteFiles: options.deleteFiles)))
                .font(.system(size: 12)).foregroundStyle(MoraStyle.muted).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(l.text("取消")) { model.pendingDeletion = nil }.keyboardShortcut(.cancelAction)
                Button(l.text(options.deleteFiles ? "删除任务和文件" : "仅删除任务"), role: .destructive) {
                    let choice = options
                    model.pendingDeletion = nil
                    model.remove(item, options: choice)
                }.keyboardShortcut(.defaultAction).disabled(model.isBusy)
            }
        }.padding(28).frame(width: 410).foregroundStyle(MoraStyle.paper)
            .background(MoraStyle.ink).tint(MoraStyle.coral).preferredColorScheme(.dark)
            .onAppear { options = RemovalOptions() }
    }
}

private struct TaskRow: View {
    let item: DownloadTask
    let l: L10n
    let busy: Bool
    let control: () -> Void
    let reveal: () -> Void
    let remove: () -> Void
    private var highlighted: Bool { item.status == "active" || item.status == "waiting" || item.status == "verifying" }
    private var foreground: Color { highlighted ? MoraStyle.ink : MoraStyle.paper }
    private var secondary: Color { highlighted ? MoraStyle.ink.opacity(0.72) : MoraStyle.muted }

    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: item.isFinished ? "checkmark" : "doc")
                .font(.system(size: 22, weight: .light)).frame(width: 44, height: 44)
                .background(highlighted ? MoraStyle.coral.opacity(0.65) : MoraStyle.muted.opacity(0.22), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 8) {
                Text(item.name).font(.system(size: 15, weight: .semibold)).lineLimit(2).help(item.name)
                HStack(spacing: 5) {
                    Text(item.backend == "ed2k" ? "ED2K" : "BT").font(.system(size: 9, weight: .semibold))
                    Text("· " + l.text(item.sizeTitle) + " · " + l.text(item.statusTitle))
                    if !item.speed.isEmpty { Text("· " + item.speed).monospacedDigit() }
                    else if !item.sources.isEmpty && !item.isFinished { Text("· " + l.format("来源 %@", item.sources)) }
                }.font(.system(size: 11)).foregroundStyle(secondary).lineLimit(1)
                HStack(spacing: 12) {
                    GeometryReader { geometry in
                        Capsule().fill(foreground.opacity(0.12))
                            .overlay(alignment: .leading) {
                                Capsule().fill(MoraStyle.coral).frame(width: geometry.size.width * item.fraction)
                            }
                    }.frame(height: 6).accessibilityLabel(l.text("下载进度")).accessibilityValue(item.progressTitle)
                    Text(item.progressTitle).font(.system(size: 11)).monospacedDigit().foregroundStyle(secondary).frame(width: 44, alignment: .trailing)
                }
            }
            if item.isFinished && !item.path.isEmpty {
                rowButton("folder", title: "在 Finder 中显示", action: reveal)
            } else if item.canControl {
                rowButton(item.status == "paused" ? "play.fill" : "pause.fill", title: item.status == "paused" ? "恢复" : "暂停", action: control).disabled(busy)
            }
            Menu { taskActions } label: { Image(systemName: "ellipsis").frame(width: 22, height: 32) }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().tint(foreground)
                .help(l.text("任务操作")).accessibilityLabel(l.text("任务操作"))
        }.padding(18).foregroundStyle(foreground)
            .background(highlighted ? MoraStyle.paper : MoraStyle.island, in: RoundedRectangle(cornerRadius: 22))
            .contextMenu { taskActions }
    }

    @ViewBuilder private var taskActions: some View {
        Button(action: reveal) { Label(l.text("在 Finder 中显示"), systemImage: "folder") }
        Divider()
        Button(l.text("复制文件名")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.name, forType: .string) }
        Button(l.text("复制任务 ID")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.id, forType: .string) }
        Divider()
        Button(role: .destructive, action: remove) { Label(l.text("删除任务…"), systemImage: "trash") }.disabled(busy)
        if !item.detail.isEmpty { Text(l.text(item.detail)) }
    }

    private func rowButton(_ symbol: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).font(.system(size: 13)).frame(width: 38, height: 38) }
            .buttonStyle(.plain).background(highlighted ? MoraStyle.coral : MoraStyle.muted.opacity(0.3), in: Circle())
            .help(l.text(title)).accessibilityLabel(l.text(title))
    }
}
