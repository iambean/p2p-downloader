"""Standalone macOS/Linux P2P command line client."""
import argparse
from collections import deque
from contextlib import contextmanager
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request

import engine

VERSION = '0.2.1'
SERVER_LIST = 'https://upd.emule-security.org/server.met'


def config(state):
    result = configparser.ConfigParser(interpolation=None)
    if not result.read(state / 'amule/config/amule.conf'):
        raise RuntimeError('尚未初始化。先运行 p2p init。')
    return result


@contextmanager
def mutation_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'cli.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个命令正在初始化或启动此实例，请稍后再试。')
        yield


def initialize(state, destination=None, port=14712):
    if not 1024 <= port <= 65535:
        raise ValueError('控制端口须在 1024–65535 之间。')
    if (state / 'amule/config/amule.conf').exists():
        incoming = Path(config(state).get('eMule', 'IncomingDir')).resolve()
        if destination and Path(destination).expanduser().resolve() != incoming:
            raise ValueError(f'此实例已使用 {incoming}。用另一个 --state-dir 创建独立实例，或在任务完成后手动迁移。')
        engine.emit({'status': 'already_configured', 'incoming': str(incoming)})
        return
    engine.setup_ed2k(state, destination or str(Path.home() / 'Downloads/P2P/ed2k'), port)


def validate_server_list(data):
    if len(data) < 5 or data[0] not in (0xE0, 0x0E):
        raise ValueError('server.met 头部无效，可能收到 HTML 错误页。')
    count = struct.unpack_from('<I', data, 1)[0]
    if not 0 < count <= 100000 or len(data) < 5 + count * 10:
        raise ValueError('server.met 为空或被截断。')
    return count


def bootstrap(state, source=None):
    conf = config(state)
    target = state / 'amule/config/server.met'
    if target.exists():
        try:
            count = validate_server_list(target.read_bytes())
        except ValueError:
            # Preserve empty or invalid files for diagnosis, never overwrite silently.
            raise RuntimeError(f'{target} 无有效服务器。请先关闭实例，将该文件改名备份后重试。')
        engine.emit({'status': 'bootstrap_present', 'servers': count})
        return
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1', conf.getint('ExternalConnect', 'ECPort'))) == 0:
            raise RuntimeError('客户端正在运行。先 p2p stop，再 p2p bootstrap，以便启动时载入服务器列表。')
    if source:
        path = Path(source).expanduser()
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError('服务器列表超过 5 MiB。')
        data = path.read_bytes()
    else:
        print('获取 eD2k 服务器列表…', file=sys.stderr, flush=True)
        with urllib.request.urlopen(SERVER_LIST, timeout=30) as response:
            if not response.geturl().startswith('https://'):
                raise RuntimeError('服务器列表请求被重定向到非 HTTPS 地址。')
            data = response.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('服务器列表超过 5 MiB。')
    count = validate_server_list(data)
    # Exclusive creation preserves state if another client creates this file.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
    engine.emit({'status': 'bootstrap_ready', 'servers': count, 'path': str(target)})


def download(state, args):
    item = engine.classify(args.source)
    if args.dry_run:
        engine.emit({'status': 'dry_run', **item, 'output': args.output,
                     'state_dir': str(state), 'network_started': False})
        return
    if item['backend'] == 'aria2':
        if args.queue_only:
            raise ValueError('--queue-only 仅适用于已运行的 ed2k 实例。')
        engine.require('aria2c')
        engine.download(state, item, args.output)
        return
    engine.require('amuled')
    engine.require('amulecmd')
    with mutation_lock(state):
        if args.queue_only:
            conf = config(state)
            if args.output and Path(args.output).expanduser().resolve() != Path(conf.get('eMule', 'IncomingDir')).resolve():
                raise ValueError('--output 与已配置的 IncomingDir 不一致。')
        else:
            initialize(state, args.output)
            bootstrap(state)
            engine.start_ed2k(state)
            engine.emit({'output': engine.ec(state, 'connect')})
        incoming = engine.output_dir(config(state).get('eMule', 'IncomingDir'))
        queue = engine.ec(state, 'show dl')
        if item['id'] not in queue.lower():
            available = shutil.disk_usage(incoming).free
            if available < item['size'] + 256 * 1024 * 1024:
                raise RuntimeError(f'磁盘空间不足：文件 {item["size"]} 字节，可用 {available} 字节，另保留 256 MiB。')
        engine.download(state, item, None)


def build_parser():
    parser = argparse.ArgumentParser(prog='p2p', description='P2P 文件下载工具：ed2k、磁力链接、torrent。')
    parser.add_argument('--version', action='version', version='p2p ' + VERSION)
    parser.add_argument('--state-dir', type=Path, default=engine.DEFAULT_STATE, help='独立状态目录（默认 ~/.local/share/p2p-downloader）')
    parser.add_argument('--json', action='store_true', help='结构化 JSON 输出（全局参数，放在子命令前）')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='检查后端和配置，不启动下载')
    inspect = sub.add_parser('inspect', help='仅解析链接或本地种子路径')
    inspect.add_argument('source')
    install = sub.add_parser('install-backend', help='安装 aMule 或 aria2 下载后端')
    install.add_argument('backend', choices=['amule', 'aria2'])
    init = sub.add_parser('init', help='创建 ed2k 独立配置，不连接网络')
    init.add_argument('-o', '--output', help='完成文件目录')
    init.add_argument('--ec-port', type=int, default=14712)
    boot = sub.add_parser('bootstrap', help='准备 ed2k 服务器列表，不启动客户端')
    boot.add_argument('--server-met', help='导入本地 server.met；默认从 HTTPS 来源获取')
    sub.add_parser('start', help='启动 ed2k 后台客户端；首次下载建议直接用 download')
    for name, help_text in [('connect', '连接 ed2k / Kad 网络'), ('disconnect', '断开 ed2k / Kad 网络'),
                            ('stop', '关闭此 ed2k 实例，保留任务和文件'), ('list', '列出 ed2k 下载队列'),
                            ('shared', '列出 ed2k 完成文件及哈希'), ('servers', '查看 ed2k 服务器')]:
        sub.add_parser(name, help=help_text)
    status = sub.add_parser('status', help='查看 ed2k 网络和进度；BT 进度在下载终端显示')
    status.add_argument('-w', '--watch', action='store_true', help='持续刷新；Ctrl+C 只退出查看')
    status.add_argument('--interval', type=float, default=5, help='刷新间隔秒数，至少 1 秒')
    for name, help_text in [('pause', '暂停指定 ed2k 文件'), ('resume', '恢复指定 ed2k 文件')]:
        action = sub.add_parser(name, help=help_text)
        action.add_argument('hash', help='32 位文件哈希（由 p2p list 获得）')
    logs = sub.add_parser('logs', help='查看 ed2k 日志末尾；BT 日志见任务目录')
    logs.add_argument('--tail', type=int, default=40)
    dl = sub.add_parser('download', aliases=['dl'], help='自动选择后端；ed2k 后台排队，BT 前台显示进度')
    dl.add_argument('source', help='完整链接或本地 .torrent 路径，必须加 shell 引号')
    dl.add_argument('-o', '--output', help='下载目录；已有 ed2k 实例须与 IncomingDir 一致')
    dl.add_argument('--dry-run', action='store_true', help='只展示计划，不创建目录、不启动网络')
    dl.add_argument('--queue-only', action='store_true', help='仅向已运行的 ed2k 实例排队，不初始化或连接网络')
    return parser


def run(args):
    state = args.state_dir.expanduser().resolve()
    if args.command == 'doctor':
        engine.emit({'version': VERSION, 'binaries': {name: engine.binary(name) for name in ('amuled', 'amulecmd', 'aria2c')},
                     'state_dir': str(state), 'amule_configured': (state / 'amule/config/amule.conf').exists()})
    elif args.command == 'inspect':
        engine.emit(engine.classify(args.source))
    elif args.command == 'install-backend':
        if args.backend == 'amule':
            import install_amule
            install_amule.main()
        elif engine.binary('aria2c'):
            engine.emit({'status': 'already_installed', 'path': engine.binary('aria2c')})
        elif sys.platform == 'darwin' and shutil.which('brew'):
            subprocess.run(['brew', 'install', 'aria2'], check=True)
        else:
            raise RuntimeError('请用系统包管理器安装 aria2，然后运行 p2p doctor。')
    elif args.command in ('init', 'bootstrap', 'start'):
        with mutation_lock(state):
            if args.command == 'init':
                initialize(state, args.output, args.ec_port)
            elif args.command == 'bootstrap':
                bootstrap(state, args.server_met)
            else:
                engine.start_ed2k(state)
    elif args.command in ('download', 'dl'):
        download(state, args)
    elif args.command == 'logs':
        if not 1 <= args.tail <= 10000:
            raise ValueError('--tail 须在 1–10000 之间。')
        logfile = state / 'amule/config/logfile'
        with logfile.open(errors='replace') as handle:
            engine.emit({'path': str(logfile), 'output': ''.join(deque(handle, args.tail))})
    elif args.command == 'status':
        if args.interval < 1:
            raise ValueError('--interval 不能小于 1 秒。')
        while True:
            engine.emit({'output': engine.ec(state, 'status'), 'queue': engine.ec(state, 'show dl')})
            if not args.watch:
                break
            time.sleep(args.interval)
    else:
        command = {'stop': 'shutdown', 'list': 'show dl', 'shared': 'show shared', 'servers': 'show servers'}.get(args.command, args.command)
        if args.command in ('pause', 'resume'):
            if not re.fullmatch(r'[a-fA-F0-9]{32}', args.hash):
                raise ValueError('请提供 p2p list 返回的 32 位文件哈希。')
            command += ' ' + args.hash
        engine.emit({'output': engine.ec(state, command)})


def main(argv=None):
    args = build_parser().parse_args(argv)
    def render(value):
        if args.json:
            print(json.dumps(value, ensure_ascii=False), flush=True)
        else:
            for key, item in value.items():
                if isinstance(item, dict):
                    print(key + ':')
                    for subkey, subvalue in item.items():
                        print(f'  {subkey}: {subvalue or "未安装"}')
                elif key in ('output', 'queue') and isinstance(item, str):
                    print(item.rstrip())
                else:
                    print(f'{key}: {item}')
            sys.stdout.flush()
    engine.emit = render
    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        print('已中断当前命令。ed2k 后台任务不受影响；BT 可使用相同来源和目录续传。', file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, configparser.Error, subprocess.SubprocessError) as exc:
        if args.json:
            print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f'错误：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
