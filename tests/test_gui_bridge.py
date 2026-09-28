import json
import contextlib
import errno
import io
import socket
import urllib.error
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_bridge as bridge

HASH = '0123456789abcdef0123456789abcdef'


class GUIBridgeTests(unittest.TestCase):
    def test_stopped_engines_are_normal_states_without_error_details(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as reserved, contextlib.redirect_stdout(io.StringIO()):
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
            reserved.close()  # A bound-but-not-listening socket can time out on macOS.
            state = Path(tmp)
            bridge.engine.setup_ed2k(state, str(state / 'incoming'), port)
            bridge.save_json(state / 'aria2-gui/rpc.json', {'port': port, 'secret': 'test'})
            ec_error = RuntimeError(f'Connection Failed. Unable to connect to 127.0.0.1:{port}')
            rpc_error = urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'Connection refused'))
            with patch('gui_bridge.engine.ec', side_effect=ec_error), patch('gui_bridge.rpc', side_effect=rpc_error):
                engines = bridge.snapshot(state)['engines']
            for item in engines:
                self.assertFalse(item['running'])
                self.assertNotIn('error', item)
                self.assertIn('未启动', item['detail'])

    def test_authentication_errors_are_not_hidden_as_stopped(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            state = Path(tmp)
            bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
            bridge.save_json(state / 'aria2-gui/rpc.json', {'port': 1, 'secret': 'test'})
            with patch('gui_bridge.engine.ec', side_effect=RuntimeError('Authentication failed')), patch('gui_bridge.rpc', side_effect=bridge.RPCError('tellActive', 1, 'Unauthorized')):
                engines = bridge.snapshot(state)['engines']
            self.assertIn('Authentication failed', engines[0]['error'])
            self.assertIn('Unauthorized', engines[1]['error'])

    def test_remove_paused_bt_clears_queue_result_and_persists_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            gid = '0123456789abcdef'
            replies = [{'status': 'paused'}, gid, {'status': 'removed'}, 'OK', 'OK']
            with patch('gui_bridge.rpc', side_effect=replies) as rpc:
                result = bridge.handle(Path(tmp), {'action': 'remove', 'backend': 'bt', 'id': gid})
            self.assertIn('文件已保留', result['message'])
            self.assertEqual([call.args[1] for call in rpc.call_args_list],
                             ['tellStatus', 'remove', 'tellStatus', 'removeDownloadResult', 'saveSession'])

    def test_remove_bt_metadata_also_removes_its_payload_child(self):
        parent, child = 'a' * 16, 'b' * 16
        replies = [{'status': 'complete', 'followedBy': [child]}, {'status': 'active'}, child,
                   {'status': 'removed'}, 'OK', 'OK', 'OK']
        with tempfile.TemporaryDirectory() as tmp, patch('gui_bridge.rpc', side_effect=replies) as rpc:
            bridge.handle(Path(tmp), {'action': 'remove', 'backend': 'bt', 'id': parent})
        self.assertEqual([call.args[2][0] for call in rpc.call_args_list if call.args[1] == 'removeDownloadResult'], [child, parent])

    def test_remove_rejects_invalid_identifier_without_rpc(self):
        with tempfile.TemporaryDirectory() as tmp, patch('gui_bridge.rpc') as rpc:
            with self.assertRaises(ValueError):
                bridge.handle(Path(tmp), {'action': 'remove', 'backend': 'bt', 'id': 'all'})
            rpc.assert_not_called()

    def test_ed2k_default_removal_preserves_partial_data_before_cancel(self):
        import contextlib
        import io
        for fallback in (False, True):
            with self.subTest(rename_fallback=fallback), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                state = Path(tmp)
                bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
                temp = state / 'incoming/.incomplete'
                (temp / '001.part').write_bytes(b'preserve every byte')
                (temp / '001.part.met').write_bytes(b'resume metadata')
                queue = f'> {HASH}\tfixture.txt\n> \t [1.0%]\t0/0\t\t\tPaused\t001.part.met\tAuto\n'
                cancelled = False
                def ec(_state, command):
                    nonlocal cancelled
                    if command == 'show dl':
                        return '' if cancelled else queue
                    if command.startswith('cancel '):
                        for part in temp.glob('001.part*'):
                            part.unlink()
                        cancelled = True
                    return 'Operation was successful.'
                link_patch = patch('file_actions.os.link', side_effect=OSError('unsupported')) if fallback else contextlib.nullcontext()
                with patch('gui_bridge.engine.ec', side_effect=ec), link_patch:
                    result = bridge.handle(state, {'action': 'remove', 'backend': 'ed2k', 'id': HASH})
                retained = Path(result['revealPath'])
                self.assertTrue(cancelled)
                self.assertEqual((retained / '001.part').read_bytes(), b'preserve every byte')
                self.assertEqual((retained / '001.part.met').read_bytes(), b'resume metadata')

    def test_completed_ed2k_removal_hides_record_and_keeps_file(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            state = Path(tmp)
            bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
            file = state / 'incoming/fixture.txt'
            file.write_bytes(b'keep me')
            def ec(_state, command):
                return f'> {HASH}\t{file}\n' if command == 'show shared' else ''
            with patch('gui_bridge.engine.ec', side_effect=ec):
                self.assertEqual(len(bridge.snapshot(state)['tasks']), 1)
                bridge.handle(state, {'action': 'remove', 'backend': 'ed2k', 'id': HASH})
                self.assertEqual(bridge.snapshot(state)['tasks'], [])
                self.assertEqual(file.read_bytes(), b'keep me')
                bridge.hide_completed(state, HASH, hidden=False)
                self.assertEqual(len(bridge.snapshot(state)['tasks']), 1)

    def test_queue_waiting_and_paused_are_not_complete(self):
        text = f'> {HASH}\t开源示例文件.zip\n> \t [12.5%]\t   0/   4\t\t\tWaiting\t001.part.met\tAuto [Hi]\n'
        item, = bridge.parse_queue(text, {HASH: {'size': 1024}})
        self.assertEqual(item['status'], 'waiting')
        self.assertEqual(item['progress'], 12.5)
        self.assertEqual(item['sources'], '0 / 4')
        self.assertEqual(item['name'], '开源示例文件.zip')
        item, = bridge.parse_queue(text.replace('Waiting', 'Paused'))
        self.assertEqual(item['status'], 'paused')

    def test_shared_requires_actual_file_and_excludes_active_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'example.txt'
            text = f'> {HASH}\t{path}\n'
            self.assertEqual(bridge.parse_shared(text, set()), [])
            path.write_text('public test fixture')
            self.assertEqual(bridge.parse_shared(text, {HASH}), [])
            item, = bridge.parse_shared(text, set())
            self.assertEqual(item['status'], 'complete')
            self.assertEqual(item['size'], path.stat().st_size)

    def test_magnet_metadata_is_not_payload_completion(self):
        self.assertIsNone(bridge.bt_task({'followedBy': ['0123456789abcdef'], 'status': 'complete'}))
        item = bridge.bt_task({'gid': '0123456789abcdef', 'status': 'complete', 'files': []})
        self.assertEqual(item['status'], 'unavailable')

    def test_bt_missing_or_wrong_sized_file_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'file.txt'
            value = {'gid': '0123456789abcdef', 'status': 'complete', 'files': [{'path': str(path), 'length': '4'}]}
            self.assertEqual(bridge.bt_task(value)['status'], 'unavailable')
            path.write_bytes(b'abc')
            self.assertEqual(bridge.bt_task(value)['status'], 'unavailable')
            path.write_bytes(b'abcd')
            self.assertEqual(bridge.bt_task(value)['status'], 'complete')

    def test_fresh_snapshot_never_starts_clients_or_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            with patch('gui_bridge.engine.start_ed2k', side_effect=AssertionError('start')), patch('gui_bridge.start_bt', side_effect=AssertionError('start')), patch('gui_bridge.engine.ec', side_effect=AssertionError('connect')):
                data = bridge.snapshot(state)
            self.assertEqual(data['tasks'], [])
            self.assertFalse(state.exists())

    def test_pause_rejects_command_injection(self):
        with tempfile.TemporaryDirectory() as tmp, patch('gui_bridge.engine.ec') as ec:
            with self.assertRaises(ValueError):
                bridge.handle(Path(tmp), {'action': 'pause', 'backend': 'ed2k', 'id': HASH + '\nshutdown'})
            ec.assert_not_called()

    def test_json_protocol_does_not_mix_cli_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(bridge.__file__)
            result = subprocess.run([sys.executable, str(script), '--state-dir', tmp],
                                    input=json.dumps({'action': 'snapshot'}), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['tasks'], [])


if __name__ == '__main__':
    unittest.main()
