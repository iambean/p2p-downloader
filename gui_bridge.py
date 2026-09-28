"""One JSON request on stdin, one JSON response on stdout for the native app.

Snapshots never start an engine. Mutations are serialized with the CLI lock.
"""
import argparse
import base64
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import cli
import engine
import file_actions


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as out:
        json.dump(value, out, ensure_ascii=False)
    tmp.replace(path)


def task(identifier, name, backend, status='waiting', progress=0, size=0, speed='', sources='', path='', detail=''):
    return dict(id=identifier, name=name, backend=backend, status=status,
                progress=max(0, min(100, progress)), size=size, speed=speed,
                sources=sources, path=path, detail=detail)


def parse_queue(text, metadata=None):
    metadata = metadata or {}
    tasks, current = [], None
    for line in text.splitlines():
        line = re.sub(r'^\s*>\s?', '', line).strip()
        header = re.match(r'^([A-Fa-f0-9]{32})\s+(.+)$', line)
        if header:
            key = header[1].lower()
            current = task(key, header[2], 'ed2k', size=metadata.get(key, {}).get('size', 0))
            tasks.append(current)
        elif current and (percentage := re.search(r'\[([\d.]+)%\]', line)):
            current['progress'] = float(percentage[1])
            if sources := re.search(r'(\d+)\s*/\s*(\d+)', line):
                current['sources'] = f'{sources[1]} / {sources[2]}'
            fields = [v.strip() for v in line.split('\t')]
            raw_status = fields[4] if len(fields) > 4 else line
            current['detail'] = raw_status
            if len(fields) > 5 and re.fullmatch(r'\d+\.part\.met', fields[5]):
                current['part_met'] = fields[5]
            status = raw_status.lower()
            if any(word in status for word in ('paused', 'stopped')):
                current['status'] = 'paused'
            elif 'error' in status:
                current['status'] = 'error'
            elif any(word in status for word in ('hash', 'complet')):
                current['status'] = 'verifying'
            elif 'download' in status or re.search(r'\d+\.?\d*\s*(?:KiB|MiB|bytes)/s', line):
                current['status'] = 'active'
            if len(fields) > 7:
                current['speed'] = fields[-1]
    return tasks


def parse_shared(text, active_ids):
    tasks = []
    for line in text.splitlines():
        line = re.sub(r'^\s*>\s?', '', line).strip()
        match = re.match(r'^([A-Fa-f0-9]{32})\s+(/.+)$', line)
        if not match or match[1].lower() in active_ids:
            continue
        path = Path(match[2])
        if path.suffix in ('.part', '.met') or not path.is_file():
            continue
        tasks.append(task(match[1].lower(), path.name, 'ed2k', 'complete', 100,
                          path.stat().st_size, path=str(path), detail='aMule 已校验的共享文件'))
    return tasks


class RPCError(RuntimeError):
    def __init__(self, method, code, message):
        super().__init__(message)
        self.method = method
        self.code = code

    def missing_gid(self, identifier):
        return self.code == 1 and re.fullmatch(
            r'GID\s*#?\s*' + re.escape(identifier) + r'\s+(?:is\s+)?not found\.?',
            str(self).strip(), re.I) is not None


def rpc(state, method, params=None):
    settings = read_json(state / 'aria2-gui/rpc.json', {})
    if not settings:
        raise RuntimeError('BT 引擎尚未启动。')
    request = urllib.request.Request(f'http://127.0.0.1:{settings["port"]}/jsonrpc',
        data=json.dumps({'jsonrpc': '2.0', 'id': 'p2p-ui', 'method': 'aria2.' + method,
                         'params': ['token:' + settings['secret']] + (params or [])}).encode(),
        headers={'Content-Type': 'application/json'})
    # Local RPC must not use a user's HTTP proxy.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # aria2 sends JSON-RPC errors with HTTP 400. urllib raises before the
        # caller can read that body, including for a successfully removed GID.
        try:
            result = json.load(exc)
        except (ValueError, UnicodeError):
            raise RuntimeError(f'BT 控制接口返回 HTTP {exc.code}，无法读取错误详情。') from exc
        finally:
            exc.close()
        if not isinstance(result, dict) or not isinstance(result.get('error'), dict):
            raise RuntimeError(f'BT 控制接口返回 HTTP {exc.code}，缺少有效的 RPC 错误详情。') from exc
    if not isinstance(result, dict):
        raise RuntimeError('BT 控制接口返回了无效响应。')
    if 'error' in result:
        detail = result['error']
        if not isinstance(detail, dict):
            raise RuntimeError('BT 控制接口返回了无效错误信息。')
        raise RPCError(method, detail.get('code'), str(detail.get('message', 'BT 操作失败')))
    if 'result' not in result:
        raise RuntimeError('BT 控制接口未返回操作结果。')
    return result['result']


def start_bt(state):
    try:
        rpc(state, 'getVersion')
        return
    except (OSError, RuntimeError):
        pass
    binary = engine.require('aria2c')
    work = state / 'aria2-gui'
    work.mkdir(parents=True, mode=0o700, exist_ok=True)
    work.chmod(0o700)
    settings = read_json(work / 'rpc.json', {})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', settings.get('port', 0)))
        port = sock.getsockname()[1]
    settings = dict(port=port, secret=settings.get('secret', secrets.token_hex(32)))
    session = work / 'session.txt'
    session.touch(mode=0o600, exist_ok=True)
    cfg = work / 'aria2.conf'
    values = {
        'enable-rpc': 'true', 'rpc-listen-all': 'false', 'rpc-listen-port': str(port),
        'rpc-secret': settings['secret'], 'rpc-allow-origin-all': 'false',
        'input-file': str(session), 'save-session': str(session), 'save-session-interval': '15',
        'force-save': 'true', 'max-download-result': '1000', 'max-concurrent-downloads': '2',
        'check-integrity': 'true', 'allow-overwrite': 'false', 'auto-file-renaming': 'false',
        'seed-time': '0', 'max-overall-upload-limit': '100K', 'file-allocation': 'none',
        'bt-save-metadata': 'true', 'log': str(work / 'aria2.log'), 'log-level': 'notice',
        'dht-file-path': str(work / 'dht.dat'), 'dht-file-path6': str(work / 'dht6.dat'),
        'dir': str(Path.home() / 'Downloads/P2P/bittorrent'),
    }
    cfg.write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
    cfg.chmod(0o600)
    save_json(work / 'rpc.json', settings)
    with (work / 'startup.log').open('ab') as log:
        proc = subprocess.Popen([binary, '--conf-path=' + str(cfg)], stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (work / 'pid').write_text(str(proc.pid))
    for _ in range(30):
        if proc.poll() is not None:
            raise RuntimeError(f'BT 引擎启动失败，请查看 {work / "startup.log"}')
        time.sleep(0.2)
        try:
            rpc(state, 'getVersion')
            return
        except (OSError, RuntimeError):
            pass
    raise RuntimeError('BT 引擎启动超时，请查看启动日志。')


def bt_task(value):
    files = value.get('files', [])
    path = files[0].get('path', '') if files else ''
    name = value.get('bittorrent', {}).get('info', {}).get('name') or Path(path).name or '正在获取磁力元数据'
    size = int(value.get('totalLength', 0))
    done = int(value.get('completedLength', 0))
    status = value.get('status', 'waiting')
    # A completed metadata download spawns another GID; it is not the payload.
    if value.get('followedBy') or value.get('status') == 'removed':
        return None
    if status == 'complete' and (not files or any(not Path(f['path']).is_file() or Path(f['path']).stat().st_size != int(f['length']) for f in files if f.get('selected', 'true') == 'true')):
        status = 'unavailable'
    rate = int(value.get('downloadSpeed', 0))
    if status == 'active' and not rate:
        status = 'waiting'
    return task(value['gid'], name, 'bt', status, 100 * done / size if size else 0, size,
                f'{rate / 1024:.0f} KiB/s' if rate else '', value.get('connections', '0'),
                path if Path(path).is_absolute() else value.get('dir', ''), value.get('errorMessage', ''))


def stop_engine(state, backend):
    if backend not in ('bt', 'ed2k'):
        raise ValueError('未知下载引擎。')
    if backend == 'bt':
        settings = read_json(state / 'aria2-gui/rpc.json', {})
        if not settings or refused_local_port(settings['port']):
            return {'message': '引擎尚未运行。'}
        port = settings['port']
        # Persist the queue before requesting an orderly shutdown. Never kill
        # an engine when authentication or saving its session fails.
        rpc(state, 'saveSession')
        rpc(state, 'shutdown')
    else:
        if not (state / 'amule/config/amule.conf').exists():
            return {'message': '引擎尚未运行。'}
        port = cli.config(state).getint('ExternalConnect', 'ECPort')
        if refused_local_port(port):
            return {'message': '引擎尚未运行。'}
        engine.ec(state, 'shutdown')
    # aMule can spend tens of seconds flushing its state on slower disks.
    # Stay within the native bridge timeout and never force-kill the process.
    deadline = time.monotonic() + 45
    while not refused_local_port(port):
        if time.monotonic() >= deadline:
            raise RuntimeError('引擎正在停止，请稍后刷新。')
        time.sleep(0.2)
    return {'message': '引擎已停止，任务和文件已保留。'}


def refused_local_port(port):
    with socket.socket() as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(('127.0.0.1', port)) == errno.ECONNREFUSED


def connection_refused(error):
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, OSError) and reason.errno == errno.ECONNREFUSED


def snapshot(state):
    result = dict(tasks=[], engines=[], downloadSpeed='0 B/s', folders={})
    metadata = read_json(state / 'gui/tasks.json', {})
    configured = (state / 'amule/config/amule.conf').exists()
    amule = dict(id='ed2k', name='eD2k', available=bool(engine.binary('amulecmd')), running=False,
                 detail='尚未配置' if not configured else '未启动')
    if configured:
        result['folders']['ed2k'] = cli.config(state).get('eMule', 'IncomingDir')
        try:
            status = engine.ec(state, 'status')
            amule['running'] = True
            net = re.search(r'eD2k:\s*([^\n]+)', status)
            amule['detail'] = net[1].strip() if net else '控制连接正常'
            speed = re.search(r'Download:\s*([^\n]+)', status)
            if speed:
                result['downloadSpeed'] = speed[1].strip()
            queue = parse_queue(engine.ec(state, 'show dl'), metadata)
            temp = Path(cli.config(state).get('eMule', 'TempDir'))
            for item in queue:
                item['path'] = str(temp / item['part_met'].removesuffix('.met')) if item.get('part_met') else str(temp)
            result['tasks'] += queue
            result['tasks'] += parse_shared(engine.ec(state, 'show shared'), {t['id'] for t in queue})
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            amule['running'] = False
            # A stopped local service is expected after reboot/explicit shutdown.
            # Do not hide authentication, protocol, or filesystem failures.
            port = cli.config(state).getint('ExternalConnect', 'ECPort')
            if f'Unable to connect to 127.0.0.1:{port}' in str(exc) and refused_local_port(port):
                amule['detail'] = '引擎未启动，可点击下方按钮启动'
            else:
                amule['detail'] = '控制连接不可用'
                amule['error'] = str(exc)
    result['engines'].append(amule)
    bt = dict(id='bt', name='BitTorrent', available=bool(engine.binary('aria2c')), running=False, detail='未启动')
    if (state / 'aria2-gui/rpc.json').exists():
        try:
            values = rpc(state, 'tellActive') + rpc(state, 'tellWaiting', [0, 1000]) + rpc(state, 'tellStopped', [0, 1000])
            bt.update(running=True, detail='就绪')
            result['tasks'] += [parsed for value in values if (parsed := bt_task(value)) is not None]
        except (OSError, RuntimeError) as exc:
            bt['running'] = False
            if connection_refused(exc):
                bt['detail'] = '引擎未启动，可点击下方按钮启动'
            else:
                bt['detail'] = '控制连接不可用'
                bt['error'] = str(exc)
    result['engines'].append(bt)
    result['folders']['bt'] = str(Path.home() / 'Downloads/P2P/bittorrent')
    hidden = read_json(state / 'gui/hidden-completed.json', [])
    result['tasks'] = [t for t in result['tasks'] if not (t['backend'] == 'ed2k' and t['status'] == 'complete' and t['id'] in hidden)]
    # Failed filesystem cleanup remains actionable even after the engine removed
    # the task. The next delete can retry cleanup or retain the remaining files.
    for path in sorted((state / 'gui/pending-cleanup').glob('*.json')):
        plan = read_json(path, {})
        if plan.get('task'):
            item = dict(plan['task'], status='error', detail='任务已停止，文件清理未完成；可再次删除重试。')
            result['tasks'] = [t for t in result['tasks'] if (t['backend'], t['id']) != (item['backend'], item['id'])]
            result['tasks'].append(item)
    return result


def hide_completed(state, identifier, hidden=True):
    path = state / 'gui/hidden-completed.json'
    values = set(read_json(path, []))
    if hidden:
        values.add(identifier)
    else:
        values.discard(identifier)
    save_json(path, sorted(values))


def cleanup_plan_path(state, backend, identifier):
    return state / 'gui/pending-cleanup' / f'{backend}-{identifier}.json'


def finish_cleanup(state, backend, identifier, records=None, item=None):
    path = cleanup_plan_path(state, backend, identifier)
    if not path.exists():
        if records is None:
            return 0
        save_json(path, {'records': records, 'task': item})
    plan = read_json(path, {})
    count = sum(Path(r['path']).is_file() for r in plan['records'])
    try:
        file_actions.trash_records(plan['records'])
    except Exception as exc:
        raise RuntimeError(f'任务已停止，但文件清理未完成：{exc} 可再次删除重试。') from exc
    path.unlink()
    return count


def finish_bt_files(state, identifier, value, delete_files):
    path = cleanup_plan_path(state, 'bt', identifier)
    if not delete_files:
        path.unlink(missing_ok=True)
        return 0
    if path.exists():
        records = read_json(path, {})['records']
    else:
        if value is None:
            return 0
        records = file_actions.bt_records(value)
    item = bt_task(value) if value else None
    if not item:
        name = (value or {}).get('bittorrent', {}).get('info', {}).get('name', '文件清理未完成')
        item = task(identifier, name, 'bt', 'error')
    if not path.exists():
        save_json(path, {'records': records, 'task': item})
    # Do not remove files still used by a different active GUI download.
    targets = {str(Path(r['path']).resolve()) for r in records}
    for other in rpc(state, 'tellActive') + rpc(state, 'tellWaiting', [0, 1000]):
        if other.get('gid') != identifier and any(str(Path(f.get('path', '')).resolve()) in targets for f in other.get('files', []) if f.get('path')):
            raise RuntimeError('其他下载任务仍在使用这些文件，文件已保留。')
    return finish_cleanup(state, 'bt', identifier, records, item)


def remove_bt(state, identifier, visited=None, delete_files=False):
    if not re.fullmatch(r'[a-fA-F0-9]{16}', identifier):
        raise ValueError('无效的 BT 任务 ID。')
    visited = visited if visited is not None else set()
    if identifier in visited:
        return 0
    visited.add(identifier)
    try:
        value = rpc(state, 'tellStatus', [identifier])
    except RPCError as exc:
        if exc.missing_gid(identifier):
            return finish_bt_files(state, identifier, None, delete_files)
        raise
    if value['status'] in ('active', 'waiting', 'paused'):
        try:
            rpc(state, 'remove', [identifier])
        except RPCError as exc:
            if exc.missing_gid(identifier):
                return finish_bt_files(state, identifier, value, delete_files)
            raise
        deadline = time.monotonic() + 8
        while True:
            try:
                value = rpc(state, 'tellStatus', [identifier])
            except RPCError as exc:
                if exc.missing_gid(identifier):
                    return finish_bt_files(state, identifier, value, delete_files)
                raise
            if value['status'] not in ('active', 'waiting', 'paused'):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('任务正在停止，请稍后刷新再删除；未删除本地文件。')
            time.sleep(0.2)
    # A magnet can finish retrieving metadata between display and deletion.
    # Its child is the same requested download and must not keep running.
    count = 0
    for child in value.get('followedBy', []):
        count += remove_bt(state, child, visited, delete_files)
    count += finish_bt_files(state, identifier, value, delete_files)
    try:
        rpc(state, 'removeDownloadResult', [identifier])
    except RPCError as exc:
        if not exc.missing_gid(identifier):
            raise
    return count


def remove_task(state, request):
    identifier = request['id'].lower()
    delete_files = request.get('delete_files') == 'true'
    if request['backend'] == 'bt':
        if not re.fullmatch(r'[a-f0-9]{16}', identifier):
            raise ValueError('无效的 BT 任务 ID。')
        try:
            count = remove_bt(state, identifier, delete_files=delete_files)
        finally:
            # Persist cancellation even if clearing a stopped result fails.
            rpc(state, 'saveSession')
        if delete_files:
            return {'message': '任务已删除，对应文件已移到废纸篓。' if count else '任务已删除，没有可定位的文件需要清理。'}
        return {'message': '任务已删除，已下载的文件已保留。'}
    if request['backend'] != 'ed2k' or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('无效的下载引擎或文件哈希。')
    pending = cleanup_plan_path(state, 'ed2k', identifier)
    if pending.exists():
        if delete_files:
            finish_cleanup(state, 'ed2k', identifier)
        else:
            pending.unlink()
        return {'message': '文件已移到废纸篓。' if delete_files else '任务已删除，剩余文件已保留。'}
    queue = parse_queue(engine.ec(state, 'show dl'))
    current = next((t for t in queue if t['id'] == identifier), None)
    if current:
        response = engine.ec(state, 'pause ' + identifier)
        if 'Operation was successful' not in response:
            raise RuntimeError('无法暂停任务，未删除文件。')
        current = next((t for t in parse_queue(engine.ec(state, 'show dl')) if t['id'] == identifier), None)
        if not current or current['status'] != 'paused':
            raise RuntimeError('任务状态已变化，请刷新后重试；未删除文件。')
        temp = cli.config(state).get('eMule', 'TempDir')
        retained = file_actions.retain_partial(temp, current.get('part_met', ''), identifier, current['name'])
        try:
            response = engine.ec(state, 'cancel ' + identifier)
            if 'Operation was successful' not in response:
                raise RuntimeError('客户端未确认删除成功，请刷新后重试。')
            if any(t['id'] == identifier for t in parse_queue(engine.ec(state, 'show dl'))):
                raise RuntimeError('任务仍在队列中，请稍后刷新。')
        except Exception:
            # Only roll back if the same task is definitely still registered.
            try:
                if any(t['id'] == identifier for t in parse_queue(engine.ec(state, 'show dl'))):
                    file_actions.restore_retained_data(retained)
            except Exception:
                pass  # Preserved data remains in the recovery directory.
            raise RuntimeError(f'无法确认取消结果，文件已保留在恢复目录：{retained}')
        metadata = read_json(state / 'gui/tasks.json', {})
        metadata.pop(identifier, None)
        save_json(state / 'gui/tasks.json', metadata)
        if delete_files:
            records = file_actions.records_for(retained.parent, [p for p in retained.iterdir() if p.is_file()])
            finish_cleanup(state, 'ed2k', identifier, records, current)
            return {'message': '任务已删除，未完成的文件和续传数据已移到废纸篓。'}
        return {'message': '任务已删除，未完成的文件和续传数据已保留。', 'revealPath': str(retained)}
    shared = parse_shared(engine.ec(state, 'show shared'), set())
    completed = next((t for t in shared if t['id'] == identifier), None)
    if not completed:
        raise RuntimeError('未找到此任务，请刷新列表。')
    if delete_files:
        incoming = cli.config(state).get('eMule', 'IncomingDir')
        records = file_actions.records_for(incoming, [completed['path']])
        finish_cleanup(state, 'ed2k', identifier, records, completed)
    hide_completed(state, identifier)
    return {'message': '任务已删除，文件已移到废纸篓。' if delete_files else '已移除完成记录，文件仍保留在原目录。'}


def handle(state, request):
    action = request.get('action', 'snapshot')
    if action == 'snapshot':
        return snapshot(state)
    with cli.mutation_lock(state):
        if action == 'stop':
            return stop_engine(state, request['backend'])
        if action == 'remove':
            return remove_task(state, request)
        if action == 'add':
            item = engine.classify(request['source'])
            destination = request.get('output') or None
            if item['backend'] == 'amule':
                engine.require('amuled')
                cli.initialize(state, destination)
                # When reusing a running client, do not bootstrap/restart it.
                try:
                    engine.ec(state, 'status')
                except RuntimeError:
                    cli.bootstrap(state)
                    engine.start_ed2k(state)
                queue = parse_queue(engine.ec(state, 'show dl'))
                completed = parse_shared(engine.ec(state, 'show shared'), {t['id'] for t in queue})
                if any(t['id'] == item['id'] for t in completed):
                    hide_completed(state, item['id'], hidden=False)
                    return {'message': '文件已存在，已恢复到完成列表。'}
                engine.ec(state, 'connect')
                incoming = engine.output_dir(cli.config(state).get('eMule', 'IncomingDir'))
                import shutil
                if item['id'] not in engine.ec(state, 'show dl').lower() and shutil.disk_usage(incoming).free < item['size'] + 256 * 1024 * 1024:
                    raise RuntimeError('下载目录空间不足。')
                engine.download(state, item, None)
                metadata = read_json(state / 'gui/tasks.json', {})
                metadata[item['id']] = dict(name=item['name'], size=item['size'])
                save_json(state / 'gui/tasks.json', metadata)
                hide_completed(state, item['id'], hidden=False)
            else:
                directory = engine.output_dir(destination or str(Path.home() / 'Downloads/P2P/bittorrent'))
                start_bt(state)
                options = {'dir': str(directory)}
                if item['protocol'] == 'torrent':
                    encoded = base64.b64encode(Path(item['source']).read_bytes()).decode()
                    rpc(state, 'addTorrent', [encoded, [], options])
                else:
                    rpc(state, 'addUri', [[item['source']], options])
                rpc(state, 'saveSession')
            return {'message': '已加入下载队列'}
        if action in ('pause', 'resume'):
            identifier = request['id']
            if request['backend'] == 'ed2k':
                if not re.fullmatch(r'[a-fA-F0-9]{32}', identifier):
                    raise ValueError('无效的文件哈希。')
                response = engine.ec(state, action + ' ' + identifier)
                if 'Operation was successful' not in response:
                    raise RuntimeError('客户端未确认操作成功，请刷新后重试。')
            elif request['backend'] == 'bt':
                if not re.fullmatch(r'[a-fA-F0-9]{16}', identifier):
                    raise ValueError('无效的 BT 任务 ID。')
                rpc(state, 'pause' if action == 'pause' else 'unpause', [identifier])
                rpc(state, 'saveSession')
            else:
                raise ValueError('未知下载引擎。')
            return {'message': '已暂停' if action == 'pause' else '已恢复'}
        if action == 'start':
            if request['backend'] == 'ed2k':
                cli.initialize(state)
                try:
                    engine.ec(state, 'status')
                except RuntimeError:
                    cli.bootstrap(state)
                    engine.start_ed2k(state)
                engine.ec(state, 'connect')
            elif request['backend'] == 'bt':
                start_bt(state)
            else:
                raise ValueError('未知下载引擎。')
            return {'message': '引擎已启动'}
        raise ValueError('未知操作。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', type=Path, default=engine.DEFAULT_STATE)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()):
            response = handle(args.state_dir.expanduser().resolve(), request)
        print(json.dumps(response, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
