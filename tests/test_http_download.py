from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import gui_bridge as bridge
import http_download as http


class HTTPProbeTests(unittest.TestCase):
    def setUp(self):
        owner = self
        self.requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_HEAD(self): self.respond(False)
            def do_GET(self): self.respond(True)
            def respond(self, body):
                owner.requests.append((self.command, self.path, self.headers.get('Range')))
                if self.path == '/redirect':
                    self.send_response(302);self.send_header('Location', '/file');self.end_headers();return
                if self.path == '/login':
                    self.send_response(403);self.end_headers();return
                if self.path == '/nohead' and not body:
                    self.send_response(405);self.end_headers();return
                self.send_response(206 if self.path == '/nohead' else 200)
                self.send_header('Content-Type', 'text/html' if self.path == '/html' else 'application/octet-stream')
                if self.path == '/file':
                    self.send_header('Content-Disposition', "attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95%20file.bin")
                if self.path == '/unsafe': self.send_header('Content-Disposition', 'attachment; filename="../escape.bin"')
                if self.path != '/unknown': self.send_header('Content-Length', '4096')
                if self.path == '/nohead':self.send_header('Content-Range', 'bytes 0-4095/3221225472')
                self.send_header('ETag', '"fixture-v1"');self.end_headers()
                if body:
                    try:self.wfile.write(b'x'*4096)
                    except (BrokenPipeError, ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_redirect_filename_and_length(self):
        r=http.probe(self.base+'/redirect')
        self.assertEqual((r['name'],r['size']),('测试 file.bin',4096))
        self.assertEqual([r[0] for r in self.requests],['HEAD','HEAD'])
    def test_head_fallback_is_bounded_and_uses_full_content_range_size(self):
        r=http.probe(self.base+'/nohead');self.assertEqual(r['size'],3*1024**3)
        self.assertEqual(self.requests[-1][2],'bytes=0-511')
    def test_login_html_and_unsafe_names_are_not_downloaded(self):
        for path, message in [('/login','登录'),('/html','网页'),('/unsafe','不安全')]:
            with self.subTest(path=path),self.assertRaisesRegex((RuntimeError,ValueError),message):http.probe(self.base+path)
    def test_unknown_length_is_not_a_fake_completed_size(self):self.assertEqual(http.probe(self.base+'/unknown')['size'],0)

class HTTPQueueTests(unittest.TestCase):
    def test_url_validation_and_dry_classification(self):
        url='HTTPS://example.org/download?signature=a%2Bb#ignored'
        with patch.object(http,'probe') as probe:
            item=engine.classify(url)
        self.assertEqual(item['source'],'https://example.org/download?signature=a%2Bb');self.assertEqual(item['protocol'],'http');probe.assert_not_called()
        for bad in ['http://','http://user:pass@example.org/file','https://h:99999/x','https://h/a b','https://h/a\nother']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):engine.classify(bad)
    def test_html_disguised_as_a_completed_binary_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'file.bin';file.write_bytes(b'<!DOCTYPE html><html>Sign in</html>')
            size=file.stat().st_size
            value=dict(gid='a'*16,status='complete',totalLength=str(size),completedLength=str(size),files=[dict(path=str(file),length=str(size),uris=[dict(uri='https://example.org/file')])])
            result=bridge.bt_task(value,dict(size=0,content_type='application/octet-stream'))
            self.assertEqual(result['status'],'error');self.assertIn('网页',result['detail'])
            result=bridge.bt_task(value,dict(size=size+1024,content_type='application/octet-stream'))
            self.assertEqual(result['status'],'error');self.assertIn('大小',result['detail'])

    def test_parallel_settings_persist_without_starting_an_engine(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge,'start_bt') as start:
            root=Path(tmp)
            bridge.handle(root,dict(action='configure',max_concurrent='4',http_connections='8'))
            self.assertEqual(bridge.transfer_settings(root),dict(max_concurrent=4,http_connections=8))
            self.assertEqual(bridge.snapshot(root)['transferSettings']['max_concurrent'],4)
            start.assert_not_called()
            with self.assertRaises(ValueError):bridge.handle(root,dict(action='configure',max_concurrent='100',http_connections='100'))
            self.assertEqual(bridge.transfer_settings(root)['http_connections'],8)

    def test_safe_large_file_options(self):
        options=http.options('large.bin')
        for key in ['continue','always-resume']:self.assertEqual(options[key],'true')
        for key in ['allow-overwrite','auto-file-renaming','follow-torrent','follow-metalink']:self.assertEqual(options[key],'false')
        self.assertEqual(options['file-allocation'],'none')
        self.assertEqual(options['split'],'4')
        self.assertEqual(http.options('file.bin',8)['max-connection-per-server'],'8')
    def test_http_snapshot_does_not_claim_waiting_for_peers(self):
        item=bridge.bt_task(dict(gid='a'*16,status='active',totalLength=str(5*1024**3),completedLength=str(3*1024**3),files=[dict(path='/tmp/large.bin',uris=[dict(uri='https://example.org/large')])]))
        self.assertEqual(item['transferProtocol'],'http');self.assertEqual(item['completedBytes'],3*1024**3)
        self.assertEqual(item['status'],'active');self.assertEqual(item['sources'],'');self.assertEqual(item['progress'],60)
    def test_existing_file_is_preserved_and_duplicate_url_not_queued_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();out=root/'files';out.mkdir();(out/'file.bin').write_bytes(b'keep me')
            calls=[];tasks={}
            def rpc(_state,method,params=None):
                calls.append((method,params))
                if method in ('tellActive','tellWaiting'):return list(tasks.values())
                if method=='tellStatus':return tasks[params[0]]
                if method=='addUri':
                    gid='a'*16;tasks[gid]={'status':'active','files':[{'path':str(out/params[1]['out'])}]};return gid
                return 'OK'
            with patch.object(bridge,'start_bt'),patch.object(http,'probe',return_value=dict(name='file.bin',size=10,etag='v1',modified=None)),patch.object(bridge,'rpc',side_effect=rpc):
                request={'action':'add','source':'https://example.org/file','output':str(out)}
                bridge.handle(root,request);result=bridge.handle(root,request)
            adds=[c for c in calls if c[0]=='addUri'];self.assertEqual(len(adds),1)
            self.assertNotEqual(adds[0][1][1]['out'],'file.bin');self.assertEqual((out/'file.bin').read_bytes(),b'keep me')
            self.assertIn('已在',result['message'])
    def test_changed_resource_never_appends_to_old_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();out=root/'files';out.mkdir();target=out/'file.bin';target.write_bytes(b'partial');Path(str(target)+'.aria2').write_bytes(b'control')
            import hashlib
            source='https://example.org/file';key=hashlib.sha256((source+'\n'+str(out)).encode()).hexdigest()
            bridge.save_json(root/'gui/http-downloads.json',{key:dict(gid='a'*16,name='file.bin',path=str(target),etag='v1',size=100)})
            with patch.object(bridge,'start_bt'),patch.object(http,'probe',return_value=dict(name='file.bin',size=100,etag='v2',modified=None)),patch.object(bridge,'rpc',side_effect=lambda _,method,params=None: {'status':'error'} if method=='tellStatus' else []) as rpc:
                with self.assertRaisesRegex(RuntimeError,'已变化'):bridge.handle(root,dict(action='add',source=source,output=str(out)))
                self.assertNotIn('addUri',[c.args[1] for c in rpc.call_args_list])
            self.assertEqual(target.read_bytes(),b'partial')

if __name__=='__main__':unittest.main()
