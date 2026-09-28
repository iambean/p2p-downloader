#!/usr/bin/env python3
"""Bump app + CLI versions; committing and pushing main triggers release."""
import argparse
from pathlib import Path
import plistlib
import re

ROOT = Path(__file__).resolve().parents[1]


def bump(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version must be MAJOR.MINOR.PATCH.')
    plist = ROOT / 'mac/Resources/Info.plist'
    info = plistlib.loads(plist.read_bytes())
    if tuple(map(int, version.split('.'))) <= tuple(map(int, info['CFBundleShortVersionString'].split('.'))):
        raise ValueError('New version must be greater than the current version.')
    info['CFBundleShortVersionString'] = version
    info['CFBundleVersion'] = str(int(info['CFBundleVersion']) + 1)
    cli = ROOT / 'cli.py'
    source, changes = re.subn(r"^VERSION = '[^']+'", f"VERSION = '{version}'", cli.read_text(), flags=re.M)
    if changes != 1:
        raise ValueError('Could not locate CLI version.')
    plist.write_bytes(plistlib.dumps(info, sort_keys=False))
    cli.write_text(source)
    print(f'Prepared {version} ({info["CFBundleVersion"]}). Commit and push main to publish.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    args = parser.parse_args()
    bump(args.version)
