#!/usr/bin/env python3
"""Optional ephemeral GitHub Actions Developer ID / notarization credentials."""
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys


def quiet(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Commands can contain keychain/import passwords. Never print their args.
        raise RuntimeError('Apple signing credential operation failed; check the configured secrets.')
    return result.stdout


def main():
    temp = Path(os.environ['RUNNER_TEMP'])
    record = temp / 'p2p-signing-state.json'
    if len(sys.argv) > 1 and sys.argv[1] == 'cleanup':
        if record.exists():
            info = json.loads(record.read_text())
            subprocess.run(['security', 'delete-keychain', info['keychain']], capture_output=True)
            for path in info['files']:
                Path(path).unlink(missing_ok=True)
            record.unlink()
        return
    names = ['APPLE_CERTIFICATE_P12', 'APPLE_CERTIFICATE_PASSWORD', 'APPLE_API_KEY_P8', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER_ID']
    values = {name: os.environ.get(name, '') for name in names}
    if not any(values.values()):
        print('No Apple signing secrets configured: using explicit ad-hoc distribution.')
        return
    if not all(values.values()):
        raise RuntimeError('Apple signing is partially configured. Supply all five Apple signing/notary secrets.')
    certificate = temp / 'p2p-certificate.p12'
    key = temp / 'p2p-notary.p8'
    keychain = temp / 'p2p-release.keychain-db'
    password = secrets.token_urlsafe(32)
    certificate.write_bytes(base64.b64decode(values['APPLE_CERTIFICATE_P12'], validate=True))
    key.write_text(values['APPLE_API_KEY_P8'])
    for path in (certificate, key):
        path.chmod(0o600)
    record.write_text(json.dumps({'keychain': str(keychain), 'files': [str(certificate), str(key)]}))
    record.chmod(0o600)
    quiet(['security', 'create-keychain', '-p', password, str(keychain)])
    quiet(['security', 'set-keychain-settings', '-lut', '21600', str(keychain)])
    quiet(['security', 'unlock-keychain', '-p', password, str(keychain)])
    quiet(['security', 'import', str(certificate), '-k', str(keychain), '-P', values['APPLE_CERTIFICATE_PASSWORD'], '-T', '/usr/bin/codesign', '-T', '/usr/bin/security'])
    quiet(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, str(keychain)])
    previous = shlex.split(quiet(['security', 'list-keychains', '-d', 'user']))
    quiet(['security', 'list-keychains', '-d', 'user', '-s', str(keychain), *previous])
    identities = quiet(['security', 'find-identity', '-v', '-p', 'codesigning', str(keychain)])
    match = re.search(r'([A-F0-9]{40}) "Developer ID Application:', identities)
    if not match:
        raise RuntimeError('The imported certificate is not a valid Developer ID Application identity.')
    with open(os.environ['GITHUB_ENV'], 'a') as out:
        out.write(f'P2P_SIGNING_IDENTITY={match[1]}\nP2P_NOTARIZE=true\nAPPLE_API_KEY_PATH={key}\n')
    print('Developer ID signing and Apple notarization configured for this runner only.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
