"""Exercise urllib's real HTTP error path, not a mocked RPC method."""
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_bridge as bridge

GID = '0123456789abcdef'


class RPCTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.calls = []
        self.missing_at = 'initial'
        self.error_message = f'GID {GID} is not found'
        self.error_code = 1
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = request['method'].removeprefix('aria2.')
                owner.calls.append(method)
                count = owner.calls.count('tellStatus')
                failure = ((method == 'tellStatus' and (owner.missing_at == 'initial' or (owner.missing_at == 'poll' and count > 1)))
                           or (method == 'removeDownloadResult' and owner.missing_at == 'result')
                           or (method == 'remove' and owner.missing_at == 'remove'))
                response = {'jsonrpc': '2.0', 'id': request['id']}
                if failure:
                    response['error'] = {'code': owner.error_code, 'message': owner.error_message}
                elif method == 'tellStatus':
                    response['result'] = {'status': 'paused' if count == 1 else 'removed'}
                else:
                    response['result'] = GID if method == 'remove' else 'OK'
                self.send_response(400 if failure else 200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        bridge.save_json(self.state / 'aria2-gui/rpc.json', {'port': self.server.server_port, 'secret': 'test-only'})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_missing_task_at_every_removal_stage_is_idempotent(self):
        for stage in ('initial', 'remove', 'poll', 'result'):
            with self.subTest(stage=stage):
                self.missing_at = stage
                self.calls.clear()
                result = bridge.handle(self.state, {'action': 'remove', 'backend': 'bt', 'id': GID})
                self.assertIn('任务已删除', result['message'])
                self.assertEqual(self.calls[-1], 'saveSession')

    def test_real_rpc_error_body_is_preserved(self):
        self.error_message = 'Unauthorized'
        with self.assertRaisesRegex(RuntimeError, 'Unauthorized'):
            bridge.rpc(self.state, 'tellStatus', [GID])

    def test_unrelated_error_is_not_treated_as_success(self):
        self.error_message = 'Download result cannot be removed'
        self.missing_at = 'result'
        with self.assertRaisesRegex(RuntimeError, 'Download result cannot be removed'):
            bridge.handle(self.state, {'action': 'remove', 'backend': 'bt', 'id': GID})


if __name__ == '__main__':
    unittest.main()
