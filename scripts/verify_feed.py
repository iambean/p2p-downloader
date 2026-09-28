#!/usr/bin/env python3
"""Verify a signed appcast with the real Sparkle client and an isolated old host."""
import http.server
from pathlib import Path
import plistlib
import subprocess
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'mac/dist'


def main():
    binary_dir = subprocess.check_output(['swift', 'build', '-c', 'release', '--arch', 'arm64', '--show-bin-path'], cwd=ROOT / 'mac', text=True).strip()
    with tempfile.TemporaryDirectory(prefix='p2p-update-probe-') as tmp:
        old = Path(tmp) / 'Old P2P.app'
        subprocess.run(['ditto', str(DIST / 'Mora.app'), str(old)], check=True)
        plist = old / 'Contents/Info.plist'
        info = plistlib.loads(plist.read_bytes())
        info['CFBundleVersion'] = '0'
        info['CFBundleShortVersionString'] = '0.0.0'
        info['CFBundleIdentifier'] = 'com.xinfan.p2p-update-probe.' + uuid.uuid4().hex
        info['SUEnableAutomaticChecks'] = False
        info['SUAutomaticallyUpdate'] = False
        plist.write_bytes(plistlib.dumps(info))
        subprocess.run(['codesign', '--force', '--sign', '-', str(old)], check=True, capture_output=True)
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(DIST), **kwargs)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subprocess.run(['xcrun', 'swift', '-F', binary_dir, '-framework', 'Sparkle',
                            '-Xlinker', '-rpath', '-Xlinker', binary_dir,
                            str(ROOT / 'scripts/ProbeUpdate.swift'), str(old),
                            f'http://127.0.0.1:{server.server_port}/appcast.xml'], check=True, timeout=50)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
