#!/usr/bin/env python3
"""Version gate, macOS release packaging, signed feed and immutable publication."""
import argparse
import base64
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'mac/dist'
APP = DIST / 'P2P Downloads.app'
SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'


def run(args, **kwargs):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def metadata(path=None):
    info = plistlib.loads((path or ROOT / 'mac/Resources/Info.plist').read_bytes())
    version, build = info['CFBundleShortVersionString'], info['CFBundleVersion']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not str(build).isdigit():
        raise ValueError('Release requires a stable semantic version and integer build number.')
    if len(base64.b64decode(info.get('SUPublicEDKey', ''), validate=True)) != 32:
        raise ValueError('A real Sparkle Ed25519 public key is required.')
    for flag in ('SUEnableAutomaticChecks', 'SUAutomaticallyUpdate', 'SUVerifyUpdateBeforeExtraction', 'SURequireSignedFeed'):
        if info.get(flag) is not True:
            raise ValueError(f'{flag} must be enabled for release.')
    return info


def api(path):
    result = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if result.returncode:
        if 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def prepare(repo):
    info = metadata()
    version, build = info['CFBundleShortVersionString'], int(info['CFBundleVersion'])
    tag = 'v' + version
    ref = os.environ.get('GITHUB_REF', '')
    if ref.startswith('refs/tags/') and ref != 'refs/tags/' + tag:
        raise ValueError('Tag does not match the source version.')
    expected_feed = f'https://github.com/{repo}/releases/latest/download/appcast.xml'
    if info['SUFeedURL'] != expected_feed:
        raise ValueError('App update feed does not match this release repository.')
    existing = api(f'repos/{repo}/releases/tags/{tag}')
    publish = existing is None or existing['draft']
    if publish:
        latest = api(f'repos/{repo}/releases/latest')
        if latest:
            previous = api(f'repos/{repo}/contents/mac/Resources/Info.plist?ref={latest["tag_name"]}')
            old = plistlib.loads(base64.b64decode(previous['content']))
            if build <= int(old['CFBundleVersion']):
                raise ValueError('Build number must increase beyond the latest published release.')
            if tuple(map(int, version.split('.'))) <= tuple(map(int, old['CFBundleShortVersionString'].split('.'))):
                raise ValueError('Version must increase beyond the latest published release.')
    result = {'publish': str(publish).lower(), 'version': version, 'build': str(build), 'tag': tag}
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as out:
            out.write(''.join(f'{k}={v}\n' for k, v in result.items()))
    print(json.dumps(result))


def notarize(path):
    result = json.loads(run(['xcrun', 'notarytool', 'submit', path, '--key', os.environ['APPLE_API_KEY_PATH'],
        '--key-id', os.environ['APPLE_API_KEY_ID'], '--issuer', os.environ['APPLE_API_ISSUER_ID'],
        '--wait', '--timeout', '15m', '--output-format', 'json']))
    if result.get('status') != 'Accepted':
        raise RuntimeError('Apple notarization was not accepted; no release will be published.')


def package():
    info = metadata(APP / 'Contents/Info.plist')
    version = info['CFBundleShortVersionString']
    for executable in ('MacOS/P2PDownloads', 'Helpers/P2PFileOps'):
        arch = run(['lipo', '-archs', APP / 'Contents' / executable])
        if arch != 'arm64':
            raise ValueError(f'{executable} must be arm64 only, got {arch}')
    run(['codesign', '--verify', '--deep', '--strict', APP])
    zip_path = DIST / f'P2P-Downloads-{version}-arm64.zip'
    dmg = DIST / f'P2P-Downloads-{version}-arm64.dmg'
    zip_path.unlink(missing_ok=True)
    run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', APP, zip_path])
    if os.environ.get('P2P_NOTARIZE') == 'true':
        notarize(zip_path)
        run(['xcrun', 'stapler', 'staple', APP])
        zip_path.unlink()
        run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', APP, zip_path])
    with tempfile.TemporaryDirectory(prefix='p2p-dmg-') as tmp:
        stage = Path(tmp)
        run(['ditto', APP, stage / APP.name])
        (stage / 'Applications').symlink_to('/Applications')
        run(['hdiutil', 'create', '-volname', 'P2P Downloads', '-srcfolder', stage, '-ov', '-format', 'UDZO', dmg])
    if os.environ.get('P2P_NOTARIZE') == 'true':
        run(['codesign', '--force', '--timestamp', '--sign', os.environ['P2P_SIGNING_IDENTITY'], dmg])
        notarize(dmg)
        run(['xcrun', 'stapler', 'staple', dmg])
    run(['hdiutil', 'verify', dmg])
    (DIST / 'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (zip_path, dmg)))
    print(json.dumps({'zip': str(zip_path), 'dmg': str(dmg)}))


def sparkle_tool(name):
    path = ROOT / 'mac/.build/artifacts/sparkle/Sparkle/bin' / name
    if not path.is_file():
        raise RuntimeError('Resolve the pinned Swift package before signing.')
    return path


def sign(repo):
    info = metadata(APP / 'Contents/Info.plist')
    version, build = info['CFBundleShortVersionString'], info['CFBundleVersion']
    archive = DIST / f'P2P-Downloads-{version}-arm64.zip'
    secret = os.environ.get('SPARKLE_EDDSA_PRIVATE_KEY', '')
    if not secret:
        raise RuntimeError('SPARKLE_EDDSA_PRIVATE_KEY is required; refusing an unsigned release.')
    tool = sparkle_tool('sign_update')
    signature = run([tool, '--ed-key-file', '-', '-p', archive], input=secret)
    run(['xcrun', 'swift', ROOT / 'scripts/VerifyUpdate.swift', archive, signature, info['SUPublicEDKey']])
    ET.register_namespace('sparkle', SPARKLE)
    feed = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(feed, 'channel')
    ET.SubElement(channel, 'title').text = 'P2P Downloads Updates'
    ET.SubElement(channel, 'link').text = f'https://github.com/{repo}/releases'
    ET.SubElement(channel, 'description').text = 'Signed Apple Silicon application updates'
    item = ET.SubElement(channel, 'item')
    ET.SubElement(item, 'title').text = f'P2P Downloads {version}'
    ET.SubElement(item, 'pubDate').text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(item, 'link').text = f'https://github.com/{repo}/releases/tag/v{version}'
    for key, value in [('version', build), ('shortVersionString', version), ('minimumSystemVersion', '13.0')]:
        ET.SubElement(item, '{' + SPARKLE + '}' + key).text = str(value)
    ET.SubElement(item, 'enclosure', {
        'url': f'https://github.com/{repo}/releases/download/v{version}/{archive.name}',
        'length': str(archive.stat().st_size), 'type': 'application/octet-stream',
        '{' + SPARKLE + '}edSignature': signature})
    ET.indent(feed)
    appcast = DIST / 'appcast.xml'
    ET.ElementTree(feed).write(appcast, encoding='utf-8', xml_declaration=True)
    run([tool, '--ed-key-file', '-', appcast], input=secret)
    run([tool, '--ed-key-file', '-', '--verify', appcast], input=secret)
    manifest = {'version': version, 'build': build, 'commit': os.environ.get('GITHUB_SHA') or run(['git', 'rev-parse', 'HEAD']),
                'architecture': 'arm64', 'signing': 'developer-id-notarized' if os.environ.get('P2P_NOTARIZE') == 'true' else 'adhoc',
                'feed': info['SUFeedURL'], 'archive': archive.name, 'ed25519_public_key': info['SUPublicEDKey']}
    (DIST / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Signed archive and appcast; verified against the embedded public key.')


def publish(repo):
    info = metadata(APP / 'Contents/Info.plist')
    version = info['CFBundleShortVersionString']
    tag = 'v' + version
    sha = os.environ.get('GITHUB_SHA') or run(['git', 'rev-parse', 'HEAD'])
    assets = [DIST / f'P2P-Downloads-{version}-arm64.zip', DIST / f'P2P-Downloads-{version}-arm64.dmg',
              DIST / 'SHA256SUMS.txt', DIST / 'appcast.xml', DIST / 'release-manifest.json']
    for path in assets:
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f'Missing release asset: {path.name}')
    ref = api(f'repos/{repo}/git/ref/tags/{tag}')
    if ref:
        obj = ref['object']
        if obj['type'] == 'tag':
            obj = api(f'repos/{repo}/git/tags/{obj["sha"]}')['object']
        if obj['sha'] != sha:
            raise RuntimeError('Existing tag points to a different commit; refusing to overwrite it.')
    else:
        run(['gh', 'api', '-X', 'POST', f'repos/{repo}/git/refs', '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + sha])
    existing = api(f'repos/{repo}/releases/tags/{tag}')
    if existing and not existing['draft']:
        raise RuntimeError('Published versions are immutable; bump the version instead.')
    notes = DIST / 'release-notes.md'
    manifest = json.loads((DIST / 'release-manifest.json').read_text())
    signing = 'Developer ID signed and notarized.' if manifest['signing'] != 'adhoc' else 'Ad-hoc signed; not Apple-notarized. On first installation macOS may require allowing the app in Privacy & Security.'
    notes.write_text(f'Apple Silicon only · macOS 13+\n\n{signing}\n\nIncludes signed Sparkle automatic updates. Existing Python 3, aMule and aria2 installations are reused.\n\nSource commit: `{sha}`\n')
    if not existing:
        run(['gh', 'release', 'create', tag, '--repo', repo, '--verify-tag', '--draft', '--title', 'P2P Downloads ' + tag, '--notes-file', notes])
    run(['gh', 'release', 'upload', tag, '--repo', repo, '--clobber', *assets])
    run(['gh', 'release', 'edit', tag, '--repo', repo, '--draft=false', '--latest'])
    # Read back the exact uploaded bytes, not just the release status.
    with tempfile.TemporaryDirectory(prefix='p2p-release-readback-') as tmp:
        run(['gh', 'release', 'download', tag, '--repo', repo, '--dir', tmp])
        for asset in assets:
            downloaded = Path(tmp) / asset.name
            if hashlib.sha256(asset.read_bytes()).digest() != hashlib.sha256(downloaded.read_bytes()).digest():
                raise RuntimeError(f'Release read-back mismatch: {asset.name}')
    print(f'https://github.com/{repo}/releases/tag/{tag}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'package', 'sign', 'publish'])
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'iambean/p2p-downloader'))
    args = parser.parse_args()
    try:
        package() if args.action == 'package' else globals()[args.action](args.repo)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
