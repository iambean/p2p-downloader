# P2P 命令行下载工具

[GitHub Releases](https://github.com/iambean/p2p-downloader/releases) · [CI/CD 与自动更新](RELEASING.md)

已有 Apple Silicon 原生图形客户端：[Mac 客户端说明](mac/README.md)。提供主窗口、Dock 图标和菜单栏入口，复用同一 ed2k 队列。

独立运行的 `p2p` 命令，不依赖 Codex 或 skill。支持 macOS/Linux、Python 3.9+；当前在 macOS Apple Silicon 验证。ed2k 使用 aMule 3.1+，BitTorrent v1 磁力链接和种子使用 aria2。v2-only、IPFS、迅雷专有链接暂不支持。

## 安装

在本目录运行：

```sh
python3 install.py
p2p --help
p2p doctor
```

安装器将 `~/.local/bin/p2p` 链接到本目录，无需 sudo、pip 或 Python 第三方包。该目录需保留；如果移动项目，再调整该软链。也可直接 `./p2p --help`。若 `~/.local/bin` 不在 PATH，使用 `~/.local/bin/p2p`。

按需安装下载后端：

```sh
p2p install-backend amule   # macOS：官方 DMG + SHA-256 验证，私有目录安装
p2p install-backend aria2   # macOS：已有安装复用，否则 Homebrew 安装
```

aMule 安装到 `~/.local/share/p2p-downloader/runtime/aMule.app`。Linux 请先安装 aMule 3.1+ 和 aria2，并放入 PATH。可用 `P2P_AMULE_BIN` 指定含 amuled/amulecmd 的目录。安装工具不会自动启动下载、建立登录启动项或修改系统安全设置。

## 下载

以下 `链接` 是占位说明，请替换为完整资源链接并保留引号：

```sh
p2p inspect '链接'                  # 只看协议、文件名、大小、哈希
p2p download --dry-run '链接'       # 只生成计划，无网络和配置写入
p2p download '链接'                 # 开始下载
p2p dl '链接'                       # download 的别名，参数完全相同
p2p download '/绝对路径/file.torrent' -o '/下载目录'
```

在 zsh/bash 中必须给完整链接加引号，推荐单引号：裸写 ed2k 中的 `|` 会被 shell 当作管道符，磁力链接中的 `&` 也有特殊含义。shell 在工具收到参数之前就会解析这些符号，因此工具无法补救未加引号的输入。

ed2k 首次下载自动创建独立配置、获取服务器列表、启动客户端并连接；已配置时复用。默认保存到 `~/Downloads/P2P/ed2k`。同一实例只使用一个完成目录；首次可用 `-o` 指定，之后不能在有任务时悄悄换目录。

磁力和种子默认保存到 `~/Downloads/P2P/bittorrent`，前台显示进度，终端关闭或 Ctrl+C 后可用相同输入和目录重新运行。保留 `.aria2` 控制文件以便续传。下载期间上传上限 100 KiB/s，完成后不继续做种；不会覆盖同名文件或自动改名。

没有自动存储盘回退：指定 `/Volumes/...` 但盘未挂载时直接报错。ed2k 入队前检查文件长度及额外 256 MiB 余量；此检查不为所有排队任务预留总空间，磁力元数据未知时也无法提前确定大小，长任务仍需关注可用容量。

## ed2k 任务管理

```sh
p2p list                           # 队列中的文件哈希、进度和来源
p2p status                         # 网络状态 + 队列
p2p status --watch                 # 每 5 秒刷新，Ctrl+C 只退出查看
p2p pause '32位文件哈希'
p2p resume '32位文件哈希'
p2p shared                         # 完成/共享文件及哈希
p2p logs --tail 50
p2p stop                           # 关闭整个 ed2k 实例，保留文件
```

这些管理命令针对 ed2k；BT 使用下载终端的进度和任务日志，并不运行额外的 RPC 服务。ed2k 下载在后台继续，关闭命令行不会取消。暂停只接受具体文件哈希，不提供隐式“全部取消”。

可按步骤配置：

```sh
p2p init -o "$HOME/Downloads/P2P/ed2k"
p2p bootstrap
p2p start
p2p connect
```

`init` 不连接网络，`bootstrap` 仅获取服务器目录。服务器列表默认来自 aMule 官方文档列出的第三方 HTTPS 地址 `https://upd.emule-security.org/server.met`；也可 `p2p bootstrap --server-met '/本地/server.met'` 导入。不覆盖已有文件；空或损坏列表先关闭实例并改名备份，再 bootstrap。新实例尚无 Kad 节点时可先通过 eD2k 获取来源。

`download --queue-only` 仅向已运行的 ed2k 实例提交，不初始化、引导或连接网络。用于手动管理的实例或离线控制测试。

## 配置、输出与故障

- 状态：`~/.local/share/p2p-downloader/`，与原 skill 的状态兼容。
- aMule 配置/日志：`amule/config/`；EC 控制接口仅监听 `127.0.0.1:14712`，凭证文件权限 0600。
- BT 日志：`aria2/<source-id>/aria2.log`。同一输入有进程锁；同一资源的 magnet 与 torrent 仍可能形成不同 ID，避免两种方式同时启动。
- JSON 输出：`p2p --json doctor`。放在子命令前；长流程每阶段一行 JSON，aria2 自己的实时输出仍为文本。
- 独立实例：`p2p --state-dir '/另一目录' init --ec-port 14713 -o '/另一完成目录'`；如要同时运行多个 aMule，还需在停止状态下为各实例配置不同的 P2P TCP/UDP 端口。
- 退出码：0 表示命令完成，1 表示工具错误，2 表示参数错误，130 表示 Ctrl+C；aria2 失败时透传其退出码。

首次启动可能等待主机名解析约一分钟。工具使用独立后台进程并保存 `amule/config/startup.log` 与 PID；提前退出会直接报错。超时先查看 PID 和日志，避免重复启动。认证失败不会被当成成功；同一状态目录的初始化/启动有进程锁。

`queued` 只说明入队。零来源、LowID 或缺块时保留任务等待，不反复删除重加。ed2k 完成需结合实际文件长度与 `shared` 哈希验证；BT `client_finished_verify_files` 提醒核对客户端完成记录和文件。不要把元数据保存成功当作资源下载完成。

aMule 的 Incoming 是共享目录，只使用专用下载目录，下载期间会与 peers 交换分片。不自动导入片库或执行下载的程序。

## 开发验证

```sh
python3 -m unittest discover -s tests -v
```

测试不访问公共 P2P 网络。另已用断开 eD2k/Kad 的临时 aMule 实例验证控制流程。公共网络真实下载速度和资源可用性取决于对应 peers，不能由这些测试保证。

协议参考：[aMule 官方文档](https://amule-org.github.io/docs)、[aria2 官方手册](https://aria2.github.io/manual/en/html/aria2c.html)。
