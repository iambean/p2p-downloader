#!/usr/bin/env python3
"""Install the official aMule macOS bundle privately; never launch it."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('This installer is for macOS. Use distro packages on Linux.')
    target = Path.home() / '.local/share/p2p-downloader/runtime/aMule.app'
    if target.exists():
        print(json.dumps({'status': 'already_present', 'path': str(target)}))
        return
    version = os.environ.get('P2P_AMULE_VERSION', '')
    endpoint = 'tags/' + version if version else 'latest'
    headers = {'User-Agent': 'p2p-downloader-cli'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    req = urllib.request.Request(
        'https://api.github.com/repos/amule-org/amule/releases/' + endpoint, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        release = json.load(response)
    asset, = [a for a in release['assets'] if a['name'].endswith('-macOS-universal2.dmg')]
    digest = asset.get('digest') or ''
    if not digest.startswith('sha256:'):
        raise RuntimeError('Release lacks SHA-256; stop and verify the release manually.')
    with tempfile.TemporaryDirectory(prefix='p2p-amule-') as tmp:
        dmg = Path(tmp) / asset['name']
        sha = hashlib.sha256()
        with urllib.request.urlopen(asset['browser_download_url'], timeout=60) as response, dmg.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                sha.update(chunk)
        if sha.hexdigest() != digest.split(':', 1)[1]:
            raise RuntimeError('SHA-256 mismatch; refusing to install.')
        attached = subprocess.check_output(['hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(dmg)])
        entities = plistlib.loads(attached)['system-entities']
        mount = next(e['mount-point'] for e in entities if 'mount-point' in e)
        try:
            source = Path(mount) / 'aMule.app'
            for name in ('amuled', 'amulecmd'):
                if not (source / 'Contents/MacOS' / name).is_file():
                    raise RuntimeError(f'Release does not contain {name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='.amule-install-', dir=target.parent))
            try:
                subprocess.run(['ditto', str(source), str(staging / 'aMule.app')], check=True)
                (staging / 'aMule.app').rename(target)
            finally:
                shutil.rmtree(staging)
        finally:
            subprocess.run(['hdiutil', 'detach', mount], check=True)
    print(json.dumps({'status': 'installed', 'version': release['tag_name'],
                      'sha256': sha.hexdigest(), 'path': str(target)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
