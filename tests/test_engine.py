"""Offline regression checks; no public P2P connection or download."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as p2p

LINK = 'ed2k://|file|%E6%B5%8B%E8%AF%95%20file.bin|123|0123456789abcdef0123456789abcdef|/'


class P2PTests(unittest.TestCase):
    def test_ed2k_unicode_and_source_extension(self):
        item = p2p.classify(LINK + '|sources,127.0.0.1:4662|/')
        self.assertEqual(item['name'], '测试 file.bin')
        self.assertEqual(item['size'], 123)
        self.assertTrue(item['source'].endswith('|sources,127.0.0.1:4662|/'))

    def test_reject_bad_and_unsafe_inputs(self):
        for source in (LINK.replace('|123|', '|-1|'), LINK.replace('|123|', '|0|'),
                       LINK.replace('%E6%B5%8B%E8%AF%95%20file.bin', '..%2Fevil'),
                       LINK.replace('%E6%B5%8B%E8%AF%95%20file.bin', '%0Aevil'),
                       LINK + '\nshutdown', LINK[:-1] + 'garbage/', 'ed2k://|server|1.2.3.4|4661|/',
                       'magnet:?xt=urn:btmh:1220' + 'a' * 64,
                       'https://example.com/file.torrent'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                p2p.classify(source)

    def test_magnet_hex_and_base32_match(self):
        hex_link = 'magnet:?xt=urn:btih:' + '0' * 40
        b32_link = 'magnet:?xt=urn:btih:' + 'A' * 32
        self.assertEqual(p2p.classify(hex_link)['id'], p2p.classify(b32_link)['id'])

    def test_profile_is_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            p2p.setup_ed2k(root, str(root / 'incoming'), 14712)
            config = root / 'amule/config/amule.conf'
            before = config.read_bytes()
            self.assertIn(b'ECAddress=127.0.0.1', before)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(RuntimeError):
                p2p.setup_ed2k(root, str(root / 'different'), 14713)
            self.assertEqual(config.read_bytes(), before)
            self.assertFalse((root / 'different').exists())

    def test_missing_volume_is_not_created(self):
        target = '/Volumes/P2P-NONEXISTENT-TEST/incoming'
        with patch('engine.os.path.ismount', return_value=False), self.assertRaises(RuntimeError):
            p2p.output_dir(target)

    def test_ec_catches_client_failure_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'amule/config').mkdir(parents=True)
            (root / 'amule/config/remote.conf').touch()
            with patch('engine.require', return_value='/fake/amulecmd'), patch('engine.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Connection Failed.', '')):
                with self.assertRaises(RuntimeError):
                    p2p.ec(root, 'status')

    def test_daemon_early_exit_fails_immediately_and_keeps_log(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            p2p.setup_ed2k(root, str(root / 'incoming'), 14712)
            with patch('engine.ec', side_effect=RuntimeError('not running')), patch('engine.socket.socket'), patch('engine.require', return_value='/fake/amuled'), patch('engine.time.sleep'), patch('engine.subprocess.Popen') as launch:
                launch.return_value.pid = 987654
                launch.return_value.returncode = 3
                launch.return_value.poll.return_value = 3
                with self.assertRaisesRegex(RuntimeError, 'exited with code 3'):
                    p2p.start_ed2k(root)
                self.assertTrue((root / 'amule/config/startup.log').exists())
                self.assertFalse((root / 'amule/config/amuled.pid').exists())
                self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_queue_dedup_and_unconfirmed_submission(self):
        item = p2p.classify(LINK)
        with patch('engine.ec', return_value=item['id']) as ec, contextlib.redirect_stdout(io.StringIO()) as out:
            p2p.download(Path('/unused'), item, None)
            self.assertEqual(ec.call_count, 1)
            self.assertIn('already_queued', out.getvalue())
        with patch('engine.ec', side_effect=['', 'Operation was successful.', '']), contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(RuntimeError):
                p2p.download(Path('/unused'), item, None)
            self.assertIn('submission_unconfirmed', out.getvalue())

    def test_bt_argument_is_literal_and_failure_propagates(self):
        source = 'magnet:?xt=urn:btih:' + 'a' * 40 + '&dn=$(echo%20bad)'
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            with patch('engine.require', return_value='/fake/aria2c'), patch('engine.subprocess.run', return_value=subprocess.CompletedProcess([], 7)) as run:
                with self.assertRaises(SystemExit) as error:
                    p2p.download(Path(directory), p2p.classify(source), str(Path(directory) / 'files'))
                self.assertEqual(error.exception.code, 7)
                argv = run.call_args.args[0]
                self.assertEqual(argv[-1], source)
                self.assertIn('--allow-overwrite=false', argv)
                self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
