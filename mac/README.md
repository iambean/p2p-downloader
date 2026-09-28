# Mora for Apple Silicon

原生 SwiftUI + AppKit 图形客户端，macOS 13+，仅构建 arm64。提供普通主窗口、Dock 图标和菜单栏入口。关闭窗口不退出应用；点击 Dock 图标可重新打开。退出应用只退出界面，后台下载引擎继续运行。

## 使用

打开 `/Applications/Mora.app`：

- 点击右上角 `+`，粘贴完整 ed2k / magnet 链接，无需命令行引号。
- 点击“导入种子”选择 `.torrent`。
- 将 ed2k／磁力链接或一个、多个 `.torrent` 文件拖进窗口，即可依次添加；拖入时显示接收提示，同一批中的重复输入会去重。不支持的项目会显示错误，其余有效项目继续添加。
- 也可把 `.torrent` 文件拖到 Dock 图标上打开；应用仅注册为备选打开方式，不主动修改系统默认种子客户端。
- 查看进度、来源、暂停/恢复任务；右键任意任务 → “在 Finder 中显示”，定位完成文件、下载中的临时文件或尚未写入文件的所在目录。
- 右键任务 → “删除任务…”：弹窗中的“同时删除已下载的文件”默认不勾选，仅移除任务并保留文件。勾选后将该任务的文件和续传数据移到废纸篓，原始种子文件及同目录其他文件保留。
- 未勾选时，未完成 ed2k 的分片和索引先保留到临时目录下的 `.p2p-retained/<任务编号>/`，再取消引擎任务；操作后可点击“查看保留的文件”。该目录可用于手动恢复，重新添加链接不会自动导入这些分片。完成的 ed2k 仅隐藏记录，再次添加同一链接可恢复显示。
- 文件清理失败时保留可重试的错误任务。再次删除可重试移到废纸篓，也可取消勾选以保留剩余文件。不会递归删除下载根目录；其他正在进行的 GUI 任务使用同一文件时会拒绝清理。
- 上方显示 eD2k / BitTorrent 引擎状态，菜单可启动或停止对应引擎。“未启动”表示后台进程未运行；“运行中”表示控制接口可用，实际传输仍取决于来源；“未就绪”表示控制连接异常。停止会保存任务并结束该协议的全部传输，重新启动后可继续；不会删除任务或文件。
- 设置 → 语言，可选跟随系统、简体中文、English；主界面立即切换，系统文件对话框和更新窗口下次启动生效。
- 选择专用下载目录。已有 ed2k 实例沿用原 IncomingDir，不能通过新任务临时迁移。

窗口采用“浮岛”深墨紫与暖珊瑚色主题，原生控件和菜单保持可访问性。默认 760 × 600，可调整大小（最小 640 × 520），文件列表独立滚动。分类标签保留任务计数，底部菜单提供引擎控制，齿轮菜单提供设置和退出。窗口可见时每 5 秒刷新，隐藏或最小化时每 60 秒刷新。没有浏览器运行时或自动登录启动项。应用使用 Sparkle 签名自动更新，可在设置菜单手动检查或关闭自动更新。

## 下载后端

应用包包含本项目的 Python 控制脚本，复用本机 Python 3、aMule 3.1+ 和 aria2，未把这些运行时捆绑进应用。当前机器已有全部依赖。复制到其他 M 系列 Mac 前需先安装这些组件：

```sh
brew install python aria2
p2p install-backend amule
```

eD2k 与命令行共用 `~/.local/share/p2p-downloader/amule`，可显示已有 CLI 队列。**程序启动和刷新只读取状态，不会自动启动、暂停或重新连接下载引擎。** 添加任务或点击启动时才执行对应操作。

重启系统或主动关闭后台后，引擎显示“未启动”属于正常状态，菜单中保留启动入口；认证失败等实际异常仍提供错误详情。开发预览只在明确传入 `--demo` / `--render-preview` 时启用，`--live` 可强制使用实际任务界面。

GUI 的 BitTorrent 使用独立的 `aria2-gui` 后台服务：仅监听本机地址，随机 RPC 凭证权限 0600，每 15 秒保存未完成任务，添加/暂停/恢复时立即保存。它不接管 CLI 原有前台 aria2 进程。同一资源不要同时从 CLI 和 GUI 发起。aria2 的已完成结果列表由运行中的引擎保留；重启引擎后不保证保留全部历史记录。

后台进程日志位于 `~/.local/share/p2p-downloader/amule/config/` 和 `~/.local/share/p2p-downloader/aria2-gui/`。aMule 是独立客户端，其自身的 Dock 图标可能仍显示。

## 构建与安装

```sh
cd p2p-downloader/mac
zsh scripts/build.sh
zsh scripts/install.sh
python3 scripts/pin_dock.py  # 可选：固定到 Dock，退出应用后仍保留
```

产物：`dist/Mora.app`。构建使用 `swift build --arch arm64`，图标由 AppKit 绘制，SwiftPM 锁定 Sparkle 版本。默认本地 ad-hoc 签名；GitHub Actions 可按 Secret 配置启用 Developer ID 签名与公证。安装脚本不覆盖其他同名应用。完整发布流程见 [RELEASING.md](../RELEASING.md)。

## 验证

```sh
swift test --arch arm64
python3 -m unittest discover -s ../tests -v
python3 ../tests/integration_gui.py
```

集成检查使用临时状态目录：关闭 eD2k/Kad 的 aMule 控制流程；关闭公共 peer 发现的 aria2 RPC；通过本机 HTTP web seed 实际下载生成的 torrent 并比对全部字节。不修改正常下载任务。

渲染带明确标识的示例界面，不启动下载：

```sh
'dist/Mora.app/Contents/MacOS/P2PDownloads' --render-preview /tmp/p2p-preview.png
```

也可用 `--demo` 打开可交互的示例界面，操作不会提交给引擎。测试时可通过 `P2P_STATE_DIR` 指向隔离状态目录。

旧版 P2P Downloads 通过相同的应用标识和签名更新源升级到 Mora，下载数据与设置保持不变。自动更新可能保留旧的 `.app` 文件名；退出应用后可在 Finder 中将其改名为 `Mora.app`。
