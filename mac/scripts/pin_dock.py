#!/usr/bin/env python3
"""Pin this app to Dock, preserving every existing item and its order."""
from pathlib import Path
import plistlib
import subprocess
from urllib.parse import unquote

app = Path('/Applications/P2P Downloads.app')
if not app.is_dir():
    raise SystemExit('请先安装应用。')


def items():
    prefs = plistlib.loads(subprocess.check_output(['defaults', 'export', 'com.apple.dock', '-']))
    return prefs.get('persistent-apps', [])


def matches(item):
    url = item.get('tile-data', {}).get('file-data', {}).get('_CFURLString', '')
    return unquote(url).removeprefix('file://').rstrip('/') == str(app)


before = items()
if any(matches(item) for item in before):
    print('已固定到 Dock。')
else:
    entry = {'tile-type': 'file-tile', 'tile-data': {
        'file-data': {'_CFURLString': app.as_uri() + '/', '_CFURLStringType': 15},
        'file-label': 'P2P Downloads'}}
    subprocess.run(['defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array-add',
                    plistlib.dumps(entry).decode()], check=True)
    after = items()
    if not any(matches(item) for item in after) or len(after) != len(before) + 1:
        raise SystemExit('Dock 写入后核验失败，请检查 Dock 设置。')
    subprocess.run(['killall', 'Dock'], check=False, capture_output=True)
    print('已固定到 Dock；原有项目顺序保留。')
