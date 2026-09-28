import AppKit
import SwiftUI
import P2PCore

struct PanelView: View {
    @ObservedObject var model: AppModel
    @State private var dropTargeted = false
    private let blue = Color(red: 0.17, green: 0.40, blue: 0.94)

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    engineStrip
                    summary
                    if model.showAdd { addForm }
                    if model.isBusy {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(model.busyMessage)
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                    }
                    if let error = model.error {
                        notice(error, symbol: "exclamationmark.triangle.fill", color: .orange) { model.error = nil }
                    } else if let feedback = model.feedback {
                        notice(feedback, symbol: "checkmark.circle.fill", color: .green) { model.feedback = nil }
                        if let path = model.retainedFilesPath {
                            Button { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } label: {
                                Label("查看保留的文件", systemImage: "folder")
                            }.font(.system(size: 11))
                        }
                    }
                    Picker("任务分类", selection: $model.filter) {
                        ForEach(TaskFilter.allCases, id: \.self) { filter in Text(filter.rawValue).tag(filter) }
                    }
                    .pickerStyle(.segmented).labelsHidden()
                    if model.filteredTasks.isEmpty { emptyState }
                    else {
                        LazyVStack(spacing: 10) {
                            ForEach(model.filteredTasks, id: \.key) { item in
                                TaskRow(item: item, busy: model.isBusy, control: {
                                    model.perform(["action": item.status == "paused" ? "resume" : "pause", "id": item.id, "backend": item.backend])
                                }, reveal: { model.reveal(item) }, remove: { model.pendingDeletion = item })
                            }
                        }
                    }
                }
                .padding(.horizontal, 20).padding(.top, 4).padding(.bottom, 18)
            }
            footer
        }
        .frame(width: 460, height: 660)
        .background(Color(nsColor: .windowBackgroundColor))
        .tint(blue)
        .sheet(item: $model.pendingDeletion) { item in
            DeleteTaskSheet(item: item, model: model)
        }
        .onDrop(of: DropSources.types, isTargeted: $dropTargeted) { providers in
            model.acceptDrop(providers)
        }
        .overlay {
            if dropTargeted {
                ZStack {
                    Color(nsColor: .windowBackgroundColor).opacity(0.94)
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(blue, style: StrokeStyle(lineWidth: 2, dash: [7, 5])).padding(12)
                    VStack(spacing: 14) {
                        Image(systemName: "tray.and.arrow.down.fill").font(.system(size: 40)).foregroundStyle(blue)
                        Text(model.isBusy ? "请等待当前操作完成" : "松开以添加下载")
                            .font(.system(size: 17, weight: .semibold))
                        Text("ed2k · 磁力链接 · .torrent 文件")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                        Text("支持一次拖入多个项目")
                            .font(.system(size: 11)).foregroundStyle(.tertiary)
                    }
                }.allowsHitTesting(false)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 11) {
            Image(systemName: "arrow.down.circle.fill")
                .font(.system(size: 31)).foregroundStyle(blue)
            VStack(alignment: .leading, spacing: 3) {
                Text("P2P 下载").font(.system(size: 17, weight: .semibold))
                Text(model.demo ? "界面预览 · 示例任务" : "轻量 P2P 下载管理")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }
            Spacer()
            if model.isRefreshing { ProgressView().controlSize(.small) }
            Button { withAnimation(.easeInOut(duration: 0.18)) { model.showAdd.toggle() } } label: {
                Image(systemName: model.showAdd ? "minus" : "plus")
                    .font(.system(size: 13, weight: .semibold)).frame(width: 29, height: 29)
                    .background(blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 9))
            }
            .buttonStyle(.plain).foregroundStyle(blue).help("添加下载")
        }
        .padding(20).padding(.bottom, -4)
    }

    private var engineStrip: some View {
        HStack(spacing: 12) {
            ForEach(model.snapshot.engines ?? []) { engine in
                HStack(spacing: 4) {
                  Circle().fill(engine.running ? Color.green : Color.secondary.opacity(0.5)).frame(width: 5, height: 5)
                  Menu(engine.name + " · " + engine.title) {
                    Text(engine.detail)
                    if let error = engine.error {
                        Button("查看错误详情") { model.error = error }
                    }
                    if engine.available && !engine.running {
                        Button("启动 \(engine.name)") { model.perform(["action": "start", "backend": engine.id]) }
                    }
                    if !engine.available { Text("请先安装 \(engine.id == "ed2k" ? "aMule" : "aria2") 下载组件") }
                  }
                  .menuStyle(.borderlessButton).font(.system(size: 10)).fixedSize()
                }.foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: 18)
    }

    private var summary: some View {
        HStack(spacing: 0) {
            stat("进行中", value: "\(model.activeCount)", symbol: "arrow.down", tint: blue)
            Divider().frame(height: 28)
            stat("已完成", value: "\(model.tasks.filter(\.isFinished).count)", symbol: "checkmark", tint: .green)
            Divider().frame(height: 28)
            stat("任务总数", value: "\(model.tasks.count)", symbol: "tray.full", tint: .secondary)
        }
        .padding(.vertical, 14)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
    }

    private func stat(_ label: String, value: String, symbol: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) { Image(systemName: symbol).foregroundStyle(tint); Text(value) }
                .font(.system(size: 18, weight: .semibold, design: .rounded)).monospacedDigit()
            Text(label).font(.system(size: 10)).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity)
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("添加下载").font(.system(size: 12, weight: .semibold))
                Spacer()
                Button("导入种子…") { model.importTorrent() }.font(.system(size: 11)).buttonStyle(.plain).foregroundStyle(blue)
            }
            TextField("粘贴 ed2k 或磁力链接，无需引号", text: $model.link, axis: .vertical)
                .textFieldStyle(.plain).font(.system(size: 12)).lineLimit(2...3)
                .padding(10).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(.primary.opacity(0.08)))
                .onSubmit { model.addLink() }
                .accessibilityLabel("下载链接")
            HStack(spacing: 8) {
                Button { model.chooseDirectory() } label: {
                    Label(model.output.isEmpty ? "默认下载目录" : URL(fileURLWithPath: model.output).lastPathComponent, systemImage: "folder")
                        .lineLimit(1).truncationMode(.middle)
                }
                .buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(.secondary)
                .help(model.output.isEmpty ? "首次下载使用 ~/Downloads/P2P，已有 ed2k 实例沿用原目录" : model.output)
                Spacer(minLength: 0)
                Button("添加任务") { model.addLink() }
                    .buttonStyle(.borderedProminent).controlSize(.small)
                    .disabled(model.isBusy || model.link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(12)
        .background(blue.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
        .disabled(model.isBusy)
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "tray.and.arrow.down").font(.system(size: 30, weight: .light)).foregroundStyle(.tertiary)
            Text(model.filter == .all ? "暂时没有可显示的任务" : "这里还没有任务")
                .font(.system(size: 13, weight: .medium))
            Text("拖入链接或种子文件，也可以点击按钮添加。")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            if !model.showAdd { Button("添加第一个任务") { model.showAdd = true }.controlSize(.small) }
        }
        .frame(maxWidth: .infinity).padding(.vertical, 34)
    }

    private func notice(_ text: String, symbol: String, color: Color, dismiss: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(text).font(.system(size: 11)).textSelection(.enabled).lineLimit(7)
            Spacer(minLength: 0)
            Button(action: dismiss) { Image(systemName: "xmark").font(.system(size: 9)) }.buttonStyle(.plain)
        }.padding(10).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 9))
    }

    private var footer: some View {
        VStack(spacing: 0) {
            Divider()
            HStack(spacing: 16) {
                Button { model.refresh() } label: { Label("刷新", systemImage: "arrow.clockwise") }
                    .disabled(model.isBusy || model.isRefreshing)
                Button { model.openFolder() } label: { Label("文件夹", systemImage: "folder") }
                Menu {
                    Button("选择下载目录…") { model.chooseDirectory() }
                    Button("恢复默认目录") { model.output = ""; UserDefaults.standard.removeObject(forKey: "outputDirectory") }
                    Divider()
                    UpdateMenuItems(updater: model.updater)
                    Text("隐藏后每分钟刷新，下载继续在后台运行。")
                    Text("退出界面不会停止下载引擎。")
                } label: { Image(systemName: "gearshape") }
                .menuStyle(.borderlessButton).fixedSize()
                Spacer()
                Button("退出") { NSApp.terminate(nil) }
                    .help("退出界面，保留后台下载")
            }
            .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
            .padding(.horizontal, 20).padding(.vertical, 13)
        }
    }
}

struct DeleteTaskSheet: View {
    let item: DownloadTask
    @ObservedObject var model: AppModel
    @State private var options = RemovalOptions()

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "trash").font(.system(size: 22)).foregroundStyle(.secondary)
                Text("删除这个任务？").font(.system(size: 17, weight: .semibold))
            }
            Text(item.name).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(3)
            Toggle("同时删除已下载的文件", isOn: $options.deleteFiles)
                .toggleStyle(.checkbox).font(.system(size: 12))
            Text(item.deletionMessage(deleteFiles: options.deleteFiles))
                .font(.system(size: 11)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button("取消") { model.pendingDeletion = nil }.keyboardShortcut(.cancelAction)
                Button(options.deleteFiles ? "删除任务和文件" : "仅删除任务", role: .destructive) {
                    let choice = options
                    model.pendingDeletion = nil
                    model.remove(item, options: choice)
                }
                .keyboardShortcut(.defaultAction).disabled(model.isBusy)
            }
        }
        .padding(24).frame(width: 380)
        .background(Color(nsColor: .windowBackgroundColor))
        .onAppear { options = RemovalOptions() }
    }
}

private struct TaskRow: View {
    let item: DownloadTask
    let busy: Bool
    let control: () -> Void
    let reveal: () -> Void
    let remove: () -> Void
    var tint: Color { item.isFinished ? .green : item.status == "paused" ? .orange : .blue }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: item.isFinished ? "checkmark.circle.fill" : "doc.zipper")
                    .font(.system(size: 17)).foregroundStyle(tint)
                    .frame(width: 30, height: 32).background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 5) {
                    Text(item.name).font(.system(size: 12, weight: .medium)).lineLimit(2).help(item.name)
                    HStack(spacing: 6) {
                        Text(item.backend == "ed2k" ? "ED2K" : "BT")
                            .font(.system(size: 8, weight: .semibold)).padding(.horizontal, 4).padding(.vertical, 2)
                            .background(.primary.opacity(0.055), in: RoundedRectangle(cornerRadius: 3))
                        Text(item.sizeTitle).font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
                if item.isFinished && !item.path.isEmpty {
                    rowButton("folder", title: "在 Finder 中显示", action: reveal)
                } else if item.canControl {
                    rowButton(item.status == "paused" ? "play.fill" : "pause.fill", title: item.status == "paused" ? "恢复" : "暂停", action: control)
                        .disabled(busy)
                }
            }
            ProgressView(value: item.fraction).tint(tint).controlSize(.small)
            HStack(spacing: 6) {
                Text(item.statusTitle).foregroundStyle(item.status == "error" ? Color.red : .secondary)
                if !item.speed.isEmpty { Text("·"); Text(item.speed).monospacedDigit() }
                else if !item.sources.isEmpty && !item.isFinished { Text("·"); Text("来源 \(item.sources)").monospacedDigit() }
                Spacer()
                Text(item.progressTitle).monospacedDigit()
            }
            .font(.system(size: 10)).foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 11))
        .overlay(RoundedRectangle(cornerRadius: 11).stroke(.primary.opacity(0.04)))
        .contextMenu {
            Button("复制文件名") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.name, forType: .string) }
            Button("复制任务 ID") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.id, forType: .string) }
            Divider()
            Button(role: .destructive, action: remove) { Label("删除任务…", systemImage: "trash") }
                .disabled(busy)
            if !item.detail.isEmpty { Text(item.detail) }
        }
    }
    private func rowButton(_ symbol: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).font(.system(size: 10)).frame(width: 25, height: 25) }
            .buttonStyle(.plain).background(.primary.opacity(0.04), in: Circle()).help(title).accessibilityLabel(title)
    }
}
