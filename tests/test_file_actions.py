import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_actions
import gui_bridge as bridge


class FileActionTests(unittest.TestCase):
    def test_rejects_root_outside_and_symlink_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'downloads'
            root.mkdir()
            outside = Path(tmp) / 'keep.txt'
            outside.write_bytes(b'untouched')
            (root / 'link').symlink_to(outside)
            for path in (root, outside, root / 'link'):
                with self.assertRaises(RuntimeError):
                    file_actions.records_for(root, [path])
            self.assertEqual(outside.read_bytes(), b'untouched')

    def test_only_selected_task_files_and_sidecar_are_trashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'downloads'
            root.mkdir()
            payload = root / 'sample.bin'
            sidecar = root / 'sample.bin.aria2'
            unrelated = root / 'keep.txt'
            payload.write_bytes(b'payload')
            sidecar.write_bytes(b'progress')
            unrelated.write_bytes(b'do not delete')
            records = file_actions.bt_records({'dir': str(root), 'files': [{'path': str(payload)}]})
            fake_trash = Path(tmp) / 'trash'
            fake_trash.mkdir()
            def helper(*args, **kwargs):
                paths = json.loads(kwargs['input'])['paths']
                for path in paths:
                    Path(path).rename(fake_trash / Path(path).name)
                return subprocess.CompletedProcess(args, 0, json.dumps({'moved': paths, 'errors': []}), '')
            with patch('file_actions.trash_helper', return_value='/fake/helper'), patch('file_actions.subprocess.run', side_effect=helper):
                file_actions.trash_records(records)
            self.assertFalse(payload.exists())
            self.assertFalse(sidecar.exists())
            self.assertEqual((fake_trash / 'sample.bin').read_bytes(), b'payload')
            self.assertEqual(unrelated.read_bytes(), b'do not delete')

    def test_changed_volume_rejects_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'fixture.txt'
            file.write_text('keep')
            records = file_actions.records_for(root, [file])
            records[0]['device'] += 1
            with self.assertRaises(RuntimeError):
                file_actions.trash_records(records)
            self.assertTrue(file.exists())

    def test_cleanup_failure_remains_visible_and_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            file = state / 'fixture.txt'
            file.write_bytes(b'keep on failure')
            identifier = 'a' * 16
            item = bridge.task(identifier, 'fixture.txt', 'bt')
            records = file_actions.records_for(state, [file])
            with patch('gui_bridge.file_actions.trash_records', side_effect=RuntimeError('trash unavailable')):
                with self.assertRaises(RuntimeError):
                    bridge.finish_cleanup(state, 'bt', identifier, records, item)
            plan = bridge.cleanup_plan_path(state, 'bt', identifier)
            self.assertTrue(plan.exists())
            self.assertEqual(bridge.snapshot(state)['tasks'][0]['status'], 'error')
            self.assertEqual(file.read_bytes(), b'keep on failure')
            with patch('gui_bridge.file_actions.trash_records'):
                bridge.finish_cleanup(state, 'bt', identifier)
            self.assertFalse(plan.exists())

    def test_other_active_task_prevents_file_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'shared.bin'
            file.write_text('in use')
            gid = 'a' * 16
            value = {'gid': gid, 'status': 'removed', 'dir': str(root), 'files': [{'path': str(file)}]}
            other = {'gid': 'b' * 16, 'files': [{'path': str(file)}]}
            with patch('gui_bridge.rpc', side_effect=[[other], []]), patch('gui_bridge.file_actions.trash_records') as trash:
                with self.assertRaisesRegex(RuntimeError, '其他下载任务'):
                    bridge.finish_bt_files(root, gid, value, True)
                trash.assert_not_called()
            self.assertTrue(file.exists())
            self.assertTrue(bridge.cleanup_plan_path(root, 'bt', gid).exists())


if __name__ == '__main__':
    unittest.main()
