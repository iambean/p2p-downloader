#!/usr/bin/env python3
"""P2P protocol routing and isolated aMule/aria2 execution (Python stdlib)."""
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, unquote, urlsplit

DEFAULT_STATE = Path.home() / '.local/share/p2p-downloader'


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def classify(source):
    source = source.strip()
    if not source or any(ord(c) < 32 or ord(c) == 127 for c in source):
        raise ValueError('Input is empty or contains control characters.')
    if source.lower().startswith('ed2k://'):
        match = re.fullmatch(r'ed2k://\|file\|([^|]+)\|([0-9]+)\|([0-9a-fA-F]{32})\|([^\r\n]*)', source, re.I)
        if not match or not re.fullmatch(r'(?:[^|\r\n]+\|)*/(?:\|sources,[^|\r\n]+\|/)?', match[4]):
            raise ValueError('Expected an ed2k file link with filename, size, 32-hex hash and trailing |/.')
        name = unquote(match[1], errors='strict')
        if name in ('.', '..') or any(c in name for c in '/\\\x00\r\n') or any(ord(c) < 32 for c in name):
            raise ValueError('Unsafe filename in ed2k link.')
        size = int(match[2])
        if size <= 0:
            raise ValueError('File size must be positive.')
        return dict(protocol='ed2k', backend='amule', name=name, size=size,
                    id=match[3].lower(), source='ed2k://' + source[7:])
    if source.lower().startswith('magnet:?'):
        query = parse_qs(urlsplit(source).query)
        hashes = [v[9:] for v in query.get('xt', []) if v.lower().startswith('urn:btih:')]
        if not hashes or not re.fullmatch(r'(?:[a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', hashes[0]):
            raise ValueError('This backend needs a BitTorrent v1 btih magnet; v2-only btmh and other magnet namespaces need another backend.')
        import base64
        digest = hashes[0].lower() if len(hashes[0]) == 40 else base64.b32decode(hashes[0].upper()).hex()
        return dict(protocol='magnet', backend='aria2', id=digest, source=source,
                    name=query.get('dn', [''])[0])
    if '://' in source:
        raise ValueError('Unsupported URL. For an HTTPS torrent URL, first save the .torrent locally; never send ed2k to aria2.')
    path = Path(source).expanduser().resolve()
    if path.suffix.lower() != '.torrent' or not path.is_file():
        raise ValueError('Expected an ed2k file link, btih magnet or existing local .torrent file.')
    return dict(protocol='torrent', backend='aria2', source=str(path), name=path.name,
                id=hashlib.sha256(path.read_bytes()).hexdigest())


def binary(name):
    private = DEFAULT_STATE / 'runtime/aMule.app/Contents/MacOS'
    for folder in (os.environ.get('P2P_AMULE_BIN'), str(private),
                   '/Applications/aMule.app/Contents/MacOS'):
        if folder and name in ('amuled', 'amulecmd'):
            candidate = Path(folder) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return shutil.which(name)


def require(name):
    result = binary(name)
    if not result:
        raise RuntimeError(f'Missing {name}; run p2p install-backend amule or p2p install-backend aria2.')
    return result


def output_dir(value):
    target = Path(value).expanduser().absolute()
    if any(c in str(target) for c in '\r\n\x00'):
        raise ValueError('Invalid output directory.')
    # Do not create a phantom /Volumes/<disk> directory on the system disk.
    if target.parts[:2] == ('/', 'Volumes'):
        if len(target.parts) < 3 or not os.path.ismount(Path('/Volumes') / target.parts[2]):
            raise RuntimeError('Requested external volume is not mounted; no local fallback was made.')
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def private_write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(content)


def setup_ed2k(state, destination, port):
    profile = state / 'amule'
    config = profile / 'config'
    if (config / 'amule.conf').exists() or (config / 'remote.conf').exists():
        raise RuntimeError('Profile already exists. Keep its settings; inspect it before making targeted changes.')
    target = output_dir(destination)
    if target in (Path.home(), Path('/')):
        raise ValueError('Use a dedicated P2P download directory, not the home or filesystem root.')
    config.mkdir(parents=True, mode=0o700, exist_ok=True)
    config.chmod(0o700)
    temp = output_dir(str(target / '.incomplete'))
    password_hash = hashlib.md5(secrets.token_bytes(32)).hexdigest()
    private_write(config / 'amule.conf', f'''[eMule]
Nick=P2PDownloader
IncomingDir={target}
TempDir={temp}
Port=4662
UDPPort=4672
MaxUpload=100
MaxDownload=0
Autoconnect=0
ConnectToKad=1
ConnectToED2K=1
UPnPEnabled=0
AddServerListFromServer=0
AddServerListFromClient=0
[ExternalConnect]
AcceptExternalConnections=1
ECAddress=127.0.0.1
ECPort={port}
ECPassword={password_hash}
UPnPECEnabled=0
[WebServer]
Enabled=0
''')
    private_write(config / 'remote.conf', f'[EC]\nHost=127.0.0.1\nPort={port}\nPassword={password_hash}\n')
    emit(dict(status='configured_not_started', profile=str(profile), incoming=str(target), ec_port=port))


def ec(state, command):
    profile = state / 'amule'
    if not (profile / 'config/remote.conf').is_file():
        raise RuntimeError('Run p2p init first.')
    # aMule 3.1 portable mode uses <cwd>/config/remote.conf. An absolute -f
    # is unsafe: this release concatenates the config directory and filename.
    result = subprocess.run([require('amulecmd'), '-l', 'en', '-c', command],
                            cwd=profile, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    if result.returncode or re.search(r'connection failed|failed to connect|authentication failed|invalid link|cannot connect|not connected to amule|FATAL ERROR|password.*incorrect|wrong password', output, re.I):
        raise RuntimeError(output.strip() or f'amulecmd exit {result.returncode}')
    return output


def start_ed2k(state):
    profile = state / 'amule'
    config = profile / 'config/amule.conf'
    if not config.is_file():
        raise RuntimeError('Run p2p init first.')
    try:
        status = ec(state, 'status')
        emit(dict(status='already_running', output=status))
        return
    except RuntimeError:
        pass
    conf = configparser.ConfigParser(interpolation=None)
    conf.read(config)
    port = conf.getint('ExternalConnect', 'ECPort')
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'EC port {port} is occupied but authentication failed. Do not start another daemon.')
    output_dir(conf.get('eMule', 'IncomingDir'))
    output_dir(conf.get('eMule', 'TempDir'))
    pidfile = config.parent / 'amuled.pid'
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text().strip()), 0)
        except (ValueError, ProcessLookupError):
            pass
        else:
            raise RuntimeError('The recorded daemon is still starting or unresponsive. Inspect its PID/log before restarting.')
    # Let Python detach the process. aMule's own fork-based --full-daemon can
    # exit during macOS initialization without ever opening the EC socket.
    startup_log = config.parent / 'startup.log'
    with startup_log.open('ab') as log:
        process = subprocess.Popen([require('amuled'), '--config-dir', str(config.parent), '--log-stdout'],
                                   cwd=profile, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    pidfile.write_text(str(process.pid) + '\n')
    pidfile.chmod(0o600)
    last_error = ''
    # macOS full-hostname lookup can take about a minute on first launch.
    for _ in range(75):
        time.sleep(1)
        if process.poll() is not None:
            pidfile.unlink(missing_ok=True)
            raise RuntimeError(f'aMuled exited with code {process.returncode}. See {startup_log}')
        try:
            emit(dict(status='running', output=ec(state, 'status')))
            return
        except RuntimeError as exc:
            last_error = str(exc)
    raise RuntimeError(f'Daemon not ready; inspect {startup_log}. Recorded PID: {process.pid}. {last_error}')


def download(state, item, destination):
    if item['backend'] == 'amule':
        if destination:
            raise ValueError('ed2k uses the IncomingDir chosen by p2p init. Do not change it per download.')
        # Read back the queue: an exit code alone does not prove acceptance.
        before = ec(state, 'show dl')
        if item['id'] in before.lower():
            emit(dict(status='already_queued', id=item['id'], output=before))
            return
        result = ec(state, 'add ' + item['source'])
        after = ec(state, 'show dl')
        emit(dict(status='queued' if item['id'] in after.lower() else 'submission_unconfirmed',
                  id=item['id'], response=result, queue=after))
        if item['id'] not in after.lower():
            raise RuntimeError('Submission was not confirmed. Inspect p2p list / p2p shared before retrying.')
        return
    target = output_dir(destination or str(Path.home() / 'Downloads/P2P/bittorrent'))
    work = state / 'aria2' / item['id']
    work.mkdir(parents=True, exist_ok=True)
    with (work / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This source already has a running download.')
        args = [require('aria2c'), '--no-conf=true', '--check-integrity=true',
                '--allow-overwrite=false', '--auto-file-renaming=false', '--seed-time=0',
                '--max-overall-upload-limit=100K', '--file-allocation=none', '--summary-interval=10',
                '--enable-rpc=false', '--bt-save-metadata=true', '--dir=' + str(target),
                '--log=' + str(work / 'aria2.log'), '--log-level=notice']
        args += ['--torrent-file=' + item['source']] if item['protocol'] == 'torrent' else [item['source']]
        emit(dict(status='starting', backend='aria2', output_dir=str(target), log=str(work / 'aria2.log')))
        result = subprocess.run(args)
        emit(dict(status='client_finished_verify_files' if result.returncode == 0 else 'incomplete_or_failed',
                  exit_code=result.returncode, output_dir=str(target), log=str(work / 'aria2.log')))
        if result.returncode:
            raise SystemExit(result.returncode)
