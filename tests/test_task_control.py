"""Control requests are idempotent despite a stale GUI snapshot."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_bridge as bridge

GID = '0123456789abcdef'

class TaskControlTests(unittest.TestCase):
    def run_control(self, action, status, transition_error=None, after=None):
        self.calls = []
        reads = 0
        def rpc(_state, method, params=None):
            nonlocal reads
            self.calls.append(method)
            if method == 'tellStatus':
                reads += 1
                return {'status': status if reads == 1 or after is None else after}
            if method in ('pause', 'unpause'):
                if transition_error: raise transition_error
                if (method == 'pause' and status == 'paused') or (method == 'unpause' and status == 'active'):
                    raise bridge.RPCError(method, 1, f'GID#{GID} cannot be {"paused" if method == "pause" else "unpaused"} now')
                return GID
            return 'OK'
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'rpc', side_effect=rpc):
            return bridge.handle(Path(tmp), {'action': action, 'backend': 'bt', 'id': GID})

    def test_repeated_pause_on_paused_task_succeeds_without_rpc_pause(self):
        self.assertIn('暂停', self.run_control('pause', 'paused')['message'])
        self.assertNotIn('pause', self.calls)
        self.assertIn('saveSession', self.calls)

    def test_repeated_resume_on_active_task_succeeds_without_rpc_unpause(self):
        self.assertIn('运行', self.run_control('resume', 'active')['message'])
        self.assertNotIn('unpause', self.calls)

    def test_pause_race_is_success_only_after_status_confirms_paused(self):
        error = bridge.RPCError('pause', 1, f'GID#{GID} cannot be paused now')
        self.assertIn('暂停', self.run_control('pause', 'active', error, 'paused')['message'])
        self.assertGreaterEqual(self.calls.count('tellStatus'), 2)

    def test_resume_race_is_success_only_after_status_confirms_running(self):
        error = bridge.RPCError('unpause', 1, f'GID#{GID} cannot be unpaused now')
        self.assertIn('恢复', self.run_control('resume', 'paused', error, 'waiting')['message'])

    def test_completed_metadata_does_not_receive_pause_or_report_paused(self):
        reply = self.run_control('pause', 'complete')
        self.assertNotIn('pause', self.calls)
        self.assertIn('变化', reply['message'])

    def test_permission_errors_are_never_hidden(self):
        error = bridge.RPCError('pause', 1, 'Unauthorized')
        with self.assertRaisesRegex(bridge.RPCError, 'Unauthorized'):
            self.run_control('pause', 'active', error, 'paused')

    def test_other_gid_or_other_error_code_is_never_hidden(self):
        for gid, code in [('f'*16, 1), (GID, 2)]:
            with self.subTest(gid=gid, code=code), self.assertRaises(bridge.RPCError):
                self.run_control('pause', 'active', bridge.RPCError('pause', code, f'GID#{gid} cannot be paused now'), 'paused')

    def test_completed_during_control_is_not_reported_as_paused(self):
        self.assertIn('变化', self.run_control('pause', 'active', after='complete')['message'])

    def test_missing_gid_triggers_refresh_without_pausing_another_task(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'rpc', side_effect=bridge.RPCError('tellStatus', 1, f'GID {GID} is not found')) as rpc:
            reply = bridge.handle(Path(tmp), {'action': 'pause', 'backend': 'bt', 'id': GID})
            self.assertIn('变化', reply['message'])
            self.assertEqual([call.args[1] for call in rpc.call_args_list], ['tellStatus'])

    def test_state_that_never_becomes_paused_does_not_report_success(self):
        error = bridge.RPCError('pause', 1, f'GID#{GID} cannot be paused now')
        with patch.object(bridge.time, 'monotonic', side_effect=[0, 10]):
            with self.assertRaisesRegex(RuntimeError, '切换'):
                self.run_control('pause', 'active', error, 'active')

if __name__ == '__main__':
    unittest.main()
