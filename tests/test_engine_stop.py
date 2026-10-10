import contextlib
import io
from pathlib import Path
import sys
import tempfile
import subprocess
import os
import signal
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_bridge as bridge


class StopEngineTests(unittest.TestCase):
    def test_managed_shutdown_verifies_identity_and_signals_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            config = state / 'amule/config';config.mkdir(parents=True)
            (config / 'amuled.pid').write_text('4242')
            command = f'/fixture/amuled --config-dir {config} --log-stdout'
            ps = subprocess.CompletedProcess([],0,f'{os.getuid()} Sat Oct 10 09:00:00 2026 {command}\n','')
            listener = subprocess.CompletedProcess([],0,'p4242\n','')
            with patch.object(bridge.engine,'binary',return_value='/fixture/amuled'), patch.object(bridge.shutil,'which',return_value='/usr/sbin/lsof'), patch.object(bridge.subprocess,'run',side_effect=[ps,listener,ps,listener]), patch.object(bridge.engine,'ec'), patch.object(bridge.os,'kill') as kill:
                self.assertTrue(bridge.request_managed_ed2k_shutdown(state,14712))
                self.assertTrue(bridge.request_managed_ed2k_shutdown(state,14712))
                kill.assert_called_once_with(4242,signal.SIGTERM)

    def test_managed_shutdown_never_signals_another_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);config=state/'amule/config';config.mkdir(parents=True)
            (config/'amuled.pid').write_text('4242')
            ps=subprocess.CompletedProcess([],0,f'{os.getuid()} Sat Oct 10 09:00:00 2026 /unrelated/process\n','')
            with patch.object(bridge.engine,'binary',return_value='/fixture/amuled'),patch.object(bridge.subprocess,'run',return_value=ps),patch.object(bridge.os,'kill') as kill:
                self.assertFalse(bridge.request_managed_ed2k_shutdown(state,14712))
                kill.assert_not_called()


    def test_ed2k_shutdown_retries_if_first_unacknowledged_request_is_lost(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            state = Path(tmp)
            bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
            commands = []
            clock = [0.0]
            def ec(*args, **kwargs):
                commands.append(args[1])
                return 'shutdown sent'
            with patch.object(bridge.engine, 'ec', side_effect=ec), patch.object(bridge, 'refused_local_port', side_effect=lambda _: len(commands) >= 2), patch.object(bridge.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(bridge.time, 'sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
                self.assertIn('已停止', bridge.handle(state, {'action': 'stop', 'backend': 'ed2k'})['message'])
            self.assertEqual(commands, ['shutdown', 'shutdown'])


    def test_ed2k_shutdown_retry_is_bounded_and_preserves_auth_errors(self):
        for auth_failure in (False, True):
            with self.subTest(auth_failure=auth_failure), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                state = Path(tmp)
                bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
                clock = [0.0]
                calls = []
                def ec(*args, **kwargs):
                    calls.append(args[1])
                    if auth_failure and len(calls) > 1:
                        raise RuntimeError('Authentication failed')
                    return 'shutdown sent'
                with patch.object(bridge.engine, 'ec', side_effect=ec), patch.object(bridge, 'refused_local_port', return_value=False), patch.object(bridge.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(bridge.time, 'sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
                    with self.assertRaisesRegex(RuntimeError, 'Authentication failed' if auth_failure else '正在停止'):
                        bridge.handle(state, {'action': 'stop', 'backend': 'ed2k'})
                self.assertEqual(len(calls), 2 if auth_failure else 5)

    def test_orderly_shutdown_can_finish_after_twelve_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            bridge.save_json(state / 'aria2-gui/rpc.json', {'port': 12345})
            with patch.object(bridge, 'refused_local_port', side_effect=[False, False, False, True]), patch.object(bridge, 'rpc'), patch.object(bridge.time, 'sleep'), patch.object(bridge.time, 'monotonic', side_effect=[0, 10, 20]):
                self.assertIn('任务和文件已保留', bridge.handle(state, {'action': 'stop', 'backend': 'bt'})['message'])

    def test_bt_persists_before_shutdown_and_waits_for_port_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            bridge.save_json(state / 'aria2-gui/rpc.json', {'port': 12345})
            with patch.object(bridge, 'refused_local_port', side_effect=[False, False, True]), patch.object(bridge, 'rpc') as rpc, patch.object(bridge.time, 'sleep'):
                result = bridge.handle(state, {'action': 'stop', 'backend': 'bt'})
            self.assertEqual([c.args[1] for c in rpc.call_args_list], ['saveSession', 'shutdown'])
            self.assertIn('任务和文件已保留', result['message'])

    def test_save_failure_never_proceeds_to_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            bridge.save_json(state / 'aria2-gui/rpc.json', {'port': 12345})
            with patch.object(bridge, 'refused_local_port', return_value=False), patch.object(bridge, 'rpc', side_effect=bridge.RPCError('saveSession', 1, 'Unauthorized')) as rpc:
                with self.assertRaises(bridge.RPCError):
                    bridge.handle(state, {'action': 'stop', 'backend': 'bt'})
                self.assertEqual([c.args[1] for c in rpc.call_args_list], ['saveSession'])

    def test_stopping_unconfigured_engine_does_not_start_it(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'rpc') as rpc, patch.object(bridge.engine, 'ec') as ec:
            for backend in ['ed2k', 'bt']:
                self.assertIn('尚未运行', bridge.handle(Path(tmp), {'action': 'stop', 'backend': backend})['message'])
            rpc.assert_not_called()
            ec.assert_not_called()

    def test_unknown_backend_never_controls_an_engine(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'start_bt') as start:
            for action in ['start', 'stop']:
                with self.assertRaises(ValueError):
                    bridge.handle(Path(tmp), {'action': action, 'backend': 'other'})
            start.assert_not_called()

    def test_finder_path_for_pending_ed2k_and_bt(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            state = Path(tmp)
            bridge.engine.setup_ed2k(state, str(state / 'incoming'), 14712)
            queue = '> ' + 'a' * 32 + '\tfixture.bin\n> \t [1.0%]\t0/0\t\t\tPaused\t001.part.met\tAuto\n'
            with patch.object(bridge.engine, 'ec', side_effect=lambda _, command: queue if command == 'show dl' else ''):
                item, = bridge.snapshot(state)['tasks']
            self.assertEqual(item['path'], str(state.resolve() / 'incoming/.incomplete/001.part'))
            bt = bridge.bt_task({'gid': 'a'*16, 'status': 'paused', 'files': [{'path': str(state / 'bt/fixture.bin')}], 'dir': str(state / 'bt')})
            self.assertEqual(bt['path'], str(state / 'bt/fixture.bin'))
            metadata = bridge.bt_task({'gid': 'b'*16, 'status': 'paused', 'files': [{'path': '[METADATA]fixture'}], 'dir': str(state / 'bt')})
            self.assertEqual(metadata['path'], str(state / 'bt'))


if __name__ == '__main__':
    unittest.main()
