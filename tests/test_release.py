import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_shipping_app_enforces_signed_automatic_updates(self):
        info = release.metadata()
        self.assertTrue(info['SURequireSignedFeed'])
        self.assertTrue(info['SUVerifyUpdateBeforeExtraction'])
        self.assertEqual(len(base64.b64decode(info['SUPublicEDKey'])), 32)
        self.assertTrue(info['SUFeedURL'].endswith('/releases/latest/download/appcast.xml'))

    def test_invalid_signing_key_fails_before_publishing(self):
        info = release.metadata()
        info['SUPublicEDKey'] = 'placeholder'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Info.plist'
            path.write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):
                release.metadata(path)

    def test_mismatched_tag_is_rejected(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/tags/v999.0.0'}), patch.object(release, 'api') as api:
            with self.assertRaisesRegex(ValueError, 'Tag'):
                release.prepare('iambean/p2p-downloader')
            api.assert_not_called()

    def test_published_version_is_skipped_not_overwritten(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/main', 'GITHUB_OUTPUT': ''}), patch.object(release, 'api', return_value={'draft': False}), contextlib.redirect_stdout(io.StringIO()) as output:
            release.prepare('iambean/p2p-downloader')
        self.assertEqual(json.loads(output.getvalue())['publish'], 'false')

    def test_release_build_cannot_go_backwards(self):
        old = release.metadata()
        old['CFBundleVersion'] = str(int(old['CFBundleVersion']) + 1)
        previous = {'content': base64.b64encode(plistlib.dumps(old)).decode()}
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/main'}), patch.object(release, 'api', side_effect=[None, {'tag_name': 'v0.1.0'}, previous]):
            with self.assertRaisesRegex(ValueError, 'Build number'):
                release.prepare('iambean/p2p-downloader')


if __name__ == '__main__':
    unittest.main()
