"""Opt-in local integration: aMule control + BT download from a loopback web seed.

Uses a fresh state directory; never touches the user's downloads or public peers.
Run: python3 p2p/tests/integration_gui.py
"""
import contextlib
import base64
import hashlib
import http.server
import io
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import gui_bridge as bridge


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def bencode(value):
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, dict):
        return b'd' + b''.join(bencode(key) + bencode(value[key]) for key in sorted(value)) + b'e'


def main():
    root = Path(tempfile.mkdtemp(prefix='p2p-gui-integration-'))
    engine.emit = lambda _: None
    engine.setup_ed2k(root, str(root / 'incoming'), port())
    config = root / 'amule/config/amule.conf'
    content = config.read_text().replace('ConnectToKad=1', 'ConnectToKad=0').replace('ConnectToED2K=1', 'ConnectToED2K=0')
    content = content.replace('Port=4662\n', f'Port={port()}\n').replace('UDPPort=4672\n', f'UDPPort={port()}\n')
    config.write_text(content)
    try:
        engine.start_ed2k(root)
        link = 'ed2k://|file|gui-control-fixture.txt|1|bde52cb31de33e46245e05fbdbd6fb24|/'
        engine.download(root, engine.classify(link), None)
        snapshot = bridge.snapshot(root)
        item, = snapshot['tasks']
        assert item['name'] == 'gui-control-fixture.txt' and item['status'] == 'waiting'
        bridge.handle(root, {'action': 'pause', 'backend': 'ed2k', 'id': item['id']})
        assert bridge.snapshot(root)['tasks'][0]['status'] == 'paused'
        assert Path(bridge.snapshot(root)['tasks'][0]['path']).name.endswith('.part')
        bridge.handle(root, {'action': 'stop', 'backend': 'ed2k'})
        assert not bridge.snapshot(root)['engines'][0]['running']
        engine.start_ed2k(root)
        assert bridge.snapshot(root)['tasks'][0]['id'] == item['id']
        assert bridge.snapshot(root)['tasks'][0]['status'] == 'paused'
        print('PASS: ed2k stop and restart preserves paused task and partial metadata.', flush=True)
        bridge.handle(root, {'action': 'resume', 'backend': 'ed2k', 'id': item['id']})
        assert 'Not connected' in engine.ec(root, 'status')
        bridge.handle(root, {'action': 'pause', 'backend': 'ed2k', 'id': item['id']})
        parts = root / 'incoming/.incomplete'
        data_path = next(parts.glob('*.part'))
        data_path.write_bytes(b'retained partial fixture')
        retained_result = bridge.handle(root, {'action': 'remove', 'backend': 'ed2k', 'id': item['id']})
        retained = Path(retained_result['revealPath'])
        assert next(retained.glob('*.part')).read_bytes() == b'retained partial fixture'
        assert not bridge.snapshot(root)['tasks']
        assert not list((root / 'incoming/.incomplete').glob('*.part'))
        print('PASS: unchecked ed2k deletion preserves partial bytes and metadata.', flush=True)
        second = 'ed2k://|file|trash-partial-fixture.txt|128|0123456789abcdef0123456789abcdef|/'
        engine.download(root, engine.classify(second), None)
        with patch('file_actions.os.link', side_effect=OSError('simulate filesystem without hardlinks')):
            bridge.handle(root, {'action': 'remove', 'backend': 'ed2k', 'id': '0123456789abcdef0123456789abcdef', 'delete_files': 'true'})
        assert not bridge.snapshot(root)['tasks']
        assert next(retained.glob('*.part')).read_bytes() == b'retained partial fixture'
        print('PASS: checked ed2k deletion moves its files to Trash; other retained data survives.', flush=True)
    finally:
        try:
            engine.ec(root, 'shutdown')
        except Exception:
            pass

    webroot = root / 'web'
    webroot.mkdir()
    payload = b'Open local P2P GUI test data.\n' * 32768
    (webroot / 'fixture.bin').write_bytes(payload)
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(webroot), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    work = root / 'aria2-gui'
    work.mkdir()
    token, rpc_port = secrets.token_hex(32), port()
    bridge.save_json(work / 'rpc.json', {'port': rpc_port, 'secret': token})
    (work / 'session.txt').touch()
    conf = work / 'offline.conf'
    conf.write_text(f'''enable-rpc=true
rpc-listen-all=false
rpc-listen-port={rpc_port}
rpc-secret={token}
enable-dht=false
enable-dht6=false
enable-peer-exchange=false
bt-enable-lpd=false
disable-ipv6=true
listen-port={port()}
seed-time=0
check-integrity=true
input-file={work / 'session.txt'}
save-session={work / 'session.txt'}
''')
    conf.chmod(0o600)
    proc = subprocess.Popen([engine.require('aria2c'), '--conf-path=' + str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                bridge.rpc(root, 'getVersion')
                break
            except OSError:
                time.sleep(0.2)
        magnet = 'magnet:?xt=urn:btih:' + 'a' * 40
        bridge.handle(root, {'action': 'add', 'source': magnet, 'output': str(root / 'bt')})
        item = next(t for t in bridge.snapshot(root)['tasks'] if t['backend'] == 'bt')
        bridge.handle(root, {'action': 'pause', 'backend': 'bt', 'id': item['id']})
        assert bridge.rpc(root, 'tellStatus', [item['id']])['status'] == 'paused'
        bridge.handle(root, {'action': 'stop', 'backend': 'bt'})
        proc.wait(timeout=10)
        assert not bridge.snapshot(root)['engines'][1]['running']
        assert 'a' * 40 in (work / 'session.txt').read_text().lower()
        proc = subprocess.Popen([engine.require('aria2c'), '--conf-path=' + str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                bridge.rpc(root, 'getVersion')
                break
            except OSError:
                time.sleep(0.2)
        assert bridge.rpc(root, 'tellStatus', [item['id']])['status'] == 'paused'
        print('PASS: BT orderly stop and restart restores saved paused task.', flush=True)
        bridge.handle(root, {'action': 'resume', 'backend': 'bt', 'id': item['id']})
        bridge.handle(root, {'action': 'remove', 'backend': 'bt', 'id': item['id']})
        # The second deletion reaches aria2's real HTTP 400 / GID-not-found path.
        bridge.handle(root, {'action': 'remove', 'backend': 'bt', 'id': item['id']})
        assert not any(t['id'] == item['id'] for t in bridge.snapshot(root)['tasks'])
        assert ('a' * 40) not in (work / 'session.txt').read_text().lower()
        print('PASS: real aria2 add / pause / resume / repeated remove and saved session, peer discovery disabled.', flush=True)
        piece_length = 16384
        torrent = {
            b'url-list': f'http://127.0.0.1:{server.server_port}/fixture.bin'.encode(),
            b'info': {b'name': b'fixture.bin', b'private': 1, b'length': len(payload), b'piece length': piece_length,
                      b'pieces': b''.join(hashlib.sha1(payload[i:i + piece_length]).digest() for i in range(0, len(payload), piece_length))}
        }
        torrent_path = root / 'fixture.torrent'
        torrent_path.write_bytes(bencode(torrent))
        bridge.handle(root, {'action': 'add', 'source': str(torrent_path), 'output': str(root / 'bt')})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            completed = [v for v in bridge.snapshot(root)['tasks'] if v['backend'] == 'bt' and v['name'] == 'fixture.bin' and v['status'] == 'complete']
            if completed:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Local web-seed download did not complete')
        assert (root / 'bt/fixture.bin').read_bytes() == payload
        bridge.handle(root, {'action': 'remove', 'backend': 'bt', 'id': completed[0]['id']})
        assert not any(t['id'] == completed[0]['id'] for t in bridge.snapshot(root)['tasks'])
        assert (root / 'bt/fixture.bin').read_bytes() == payload
        print('PASS: deleting completed BT record preserves every downloaded byte.', flush=True)
        bridge.handle(root, {'action': 'add', 'source': str(torrent_path), 'output': str(root / 'bt')})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            completed = [v for v in bridge.snapshot(root)['tasks'] if v['backend'] == 'bt' and v['name'] == 'fixture.bin' and v['status'] == 'complete']
            if completed:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Recheck of retained BT file did not complete')
        unrelated = root / 'bt/keep-this-file.txt'
        unrelated.write_bytes(b'unrelated file')
        bridge.handle(root, {'action': 'remove', 'backend': 'bt', 'id': completed[0]['id'], 'delete_files': 'true'})
        assert not (root / 'bt/fixture.bin').exists()
        assert unrelated.read_bytes() == b'unrelated file'
        print('PASS: checked BT deletion trashes payload; unrelated files remain intact.', flush=True)
        partial_gid = bridge.rpc(root, 'addTorrent', [base64.b64encode(torrent_path.read_bytes()).decode(), [], {'dir': str(root / 'bt'), 'pause': 'true'}])
        (root / 'bt/fixture.bin').write_bytes(payload[:30000])
        (root / 'bt/fixture.bin.aria2').write_bytes(b'test-only partial control file')
        bridge.handle(root, {'action': 'remove', 'backend': 'bt', 'id': partial_gid, 'delete_files': 'true'})
        assert not (root / 'bt/fixture.bin').exists()
        assert not (root / 'bt/fixture.bin.aria2').exists()
        assert unrelated.read_bytes() == b'unrelated file'
        assert torrent_path.is_file()
        print('PASS: checked paused BT deletion trashes partial payload and sidecar, preserves original torrent.', flush=True)
        print(f'PASS: real local torrent download, {len(payload)} bytes verified; no public P2P peers.', flush=True)
    finally:
        try:
            bridge.rpc(root, 'shutdown')
            proc.wait(timeout=5)
        except Exception:
            proc.terminate()
            proc.wait(timeout=5)
        server.shutdown()
    print('INTEGRATION_PASS', root, flush=True)


if __name__ == '__main__':
    main()
