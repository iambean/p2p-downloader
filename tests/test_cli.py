import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli

LINK = 'ed2k://|file|fixture.txt|25|0123456789abcdef0123456789abcdef|/'


class CLITests(unittest.TestCase):
    def test_dry_run_has_no_state_or_network_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as output:
            state = Path(tmp) / 'state'
            with patch('cli.urllib.request.urlopen', side_effect=AssertionError('network')), patch('cli.engine.ec', side_effect=AssertionError('client')):
                self.assertEqual(cli.main(['--state-dir', str(state), '--json', 'download', '--dry-run', LINK]), 0)
            self.assertFalse(state.exists())
            self.assertFalse(json.loads(output.getvalue())['network_started'])

    def test_init_reuse_preserves_password_and_rejects_directory_change(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            state = Path(tmp) / 'state'
            args = ['--state-dir', str(state), 'init', '-o', str(Path(tmp) / 'incoming')]
            self.assertEqual(cli.main(args), 0)
            config = state / 'amule/config/amule.conf'
            original = config.read_bytes()
            self.assertEqual(cli.main(args), 0)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(cli.main(['--state-dir', str(state), 'init', '-o', str(Path(tmp) / 'elsewhere')]), 1)
            self.assertEqual(config.read_bytes(), original)

    def test_bootstrap_header_and_truncation(self):
        sample = b'\xe0' + struct.pack('<I', 1) + b'\x00' * 10
        self.assertEqual(cli.validate_server_list(sample), 1)
        for invalid in (b'<html>403</html>', b'\xe0' + b'\x00' * 4, sample[:-1]):
            with self.assertRaises(ValueError):
                cli.validate_server_list(invalid)

    def test_existing_bootstrap_never_downloads_or_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            state = Path(tmp)
            cli.initialize(state, str(state / 'incoming'))
            target = state / 'amule/config/server.met'
            sample = b'\xe0' + struct.pack('<I', 1) + b'\x00' * 10
            target.write_bytes(sample)
            with patch('cli.urllib.request.urlopen', side_effect=AssertionError('network')):
                cli.bootstrap(state)
            self.assertEqual(target.read_bytes(), sample)

    def test_pause_never_sends_all_or_command_injection(self):
        with patch('cli.engine.ec') as ec, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['pause', 'all']), 1)
            self.assertEqual(cli.main(['pause', 'a' * 32 + '\nshutdown']), 1)
            ec.assert_not_called()

    def test_missing_backend_error_is_clean(self):
        with patch('cli.engine.require', side_effect=RuntimeError('Missing amuled')), contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(['download', LINK]), 1)
            self.assertIn('Missing amuled', error.getvalue())
            self.assertNotIn('Traceback', error.getvalue())

    def test_entrypoint_runs_from_unrelated_directory(self):
        path = Path(__file__).resolve().parents[1] / 'p2p'
        result = subprocess.run([sys.executable, str(path), '--version'], cwd='/', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'p2p ' + cli.VERSION)


if __name__ == '__main__':
    unittest.main()
