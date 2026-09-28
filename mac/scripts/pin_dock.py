#!/usr/bin/env python3
"""Pin this app to Dock, preserving every existing item and its order."""
from pathlib import Path
import plistlib
import subprocess
from urllib.parse import unquote

app = Path('/Applications/Mora.app')
if not app.is_dir():
    raise SystemExit('请先安装应用。')


def items():
    prefs = plistlib.loads(subprocess.check_output(['defaults', 'export', 'com.apple.dock', '-']))
    return prefs.get('persistent-apps', [])


def matches(item):
    url = item.get('tile-data', {}).get('file-data', {}).get('_CFURLString', '')
    return unquote(url).removeprefix('file://').rstrip('/') in (str(app), '/Applications/P2P Downloads.app')


before = items()
entry = {'tile-type': 'file-tile', 'tile-data': {
    'file-data': {'_CFURLString': app.as_uri() + '/', '_CFURLStringType': 15},
    'file-label': 'Mora', 'bundle-identifier': 'com.xinfan.p2p-downloads'}}
updated = []
replaced = False
for item in before:
    if matches(item):
        if not replaced:
            updated.append(entry)
            replaced = True
    else:
        updated.append(item)
if not replaced:
    updated.append(entry)
if updated != before:
    subprocess.run(['defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array',
                    *[plistlib.dumps(item).decode() for item in updated]], check=True)
    after = items()
    if after != updated:
        raise SystemExit('Dock 写入后核验失败，请检查 Dock 设置。')
    subprocess.run(['killall', 'Dock'], check=False, capture_output=True)
print('Mora 已固定到 Dock；原有位置和其他项目保留。')
