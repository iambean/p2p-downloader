import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_bridge as bridge


class StopEngineTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
