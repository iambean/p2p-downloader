"""Real HTTP transfers against loopback only, including a >2 GiB resource.

Checks pause/resume, daemon restart, network retry, no-range preservation,
redirect/filename handling, SHA-256, and a 64-bit UI snapshot. No public peers.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
from functools import lru_cache
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import gui_bridge as bridge

CHUNK = 1024**2
@lru_cache(maxsize=8)
def block(index):
    return hashlib.sha256(index.to_bytes(8, 'big')).digest() * (CHUNK // 32)
LARGE = 2 * 1024**3 + 65537
SMALL = 8 * 1024**2 + 31


def expected_hash(size):
    h=hashlib.sha256()
    for index in range(size//CHUNK):h.update(block(index))
    h.update(block(size//CHUNK)[:size%CHUNK])
    return h.hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024**2):h.update(chunk)
    return h.hexdigest()


def wait_status(state,gid,wanted,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=bridge.rpc(state,'tellStatus',[gid])
        if value['status'] in wanted:return value
        if value['status']=='error':raise AssertionError(value.get('errorMessage'))
        time.sleep(.1)
    raise AssertionError('Download did not reach expected state')


def main():
    requests=[];slow=True;deny=False
    active={};peak={};counts_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):pass
        def do_HEAD(self):self.respond(False)
        def do_GET(self):self.respond(True)
        def respond(self,body):
            nonlocal slow,deny
            path=self.path.split('?')[0]
            if path=='/redirect':
                self.send_response(302);self.send_header('Location','/large');self.end_headers();return
            if path=='/retry' and body and deny:
                self.send_response(403);self.end_headers();return
            size=LARGE if path=='/large' else 64*1024**2 if path.startswith('/parallel') else SMALL
            start,end=0,size-1
            raw=self.headers.get('Range','')
            if raw and path!='/no-range':
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',raw)
                if not match:self.send_response(416);self.end_headers();return
                start=int(match[1]);end=min(size-1,int(match[2]) if match[2] else size-1)
            status=206 if raw and path!='/no-range' else 200
            self.send_response(status)
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Disposition',f'attachment; filename="{path.strip("/")}.bin"')
            self.send_header('ETag','"fixture-'+path.strip('/')+'"')
            self.send_header('Content-Length',str(end-start+1))
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not body:return
            requests.append((path,start))
            with counts_lock:
                active[path]=active.get(path,0)+1;peak[path]=max(peak.get(path,0),active[path])
            try:
                position=start
                while position<=end:
                    n=min(65536,end-position+1,CHUNK-(position%CHUNK))
                    self.wfile.write(block(position//CHUNK)[position%CHUNK:position%CHUNK+n]);position+=n
                    if slow:time.sleep(.004)
            except (BrokenPipeError,ConnectionResetError):pass
            finally:
                with counts_lock:active[path]-=1
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    proc=None
    with tempfile.TemporaryDirectory(prefix='mora-http-integration-') as tmp:
        root=Path(tmp).resolve();work=root/'aria2-gui';work.mkdir();out=root/'files';out.mkdir()
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        token=secrets.token_hex(32);bridge.save_json(work/'rpc.json',dict(port=port,secret=token))
        session=work/'session.txt';session.touch()
        conf=work/'offline.conf';conf.write_text(f'enable-rpc=true\nrpc-listen-all=false\nrpc-listen-port={port}\nrpc-secret={token}\nenable-dht=false\nenable-dht6=false\nenable-peer-exchange=false\nbt-enable-lpd=false\ninput-file={session}\nsave-session={session}\nforce-save=true\nfile-allocation=none\n')
        conf.chmod(0o600)
        def start():
            p=subprocess.Popen([engine.require('aria2c'),'--conf-path='+str(conf)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(50):
                try:bridge.rpc(root,'getVersion');return p
                except OSError:time.sleep(.1)
            raise AssertionError('aria2 startup failed')
        def add(path):
            bridge.handle(root,dict(action='add',source=f'http://127.0.0.1:{server.server_port}'+path,output=str(out)))
            records=bridge.read_json(root/'gui/http-downloads.json',{})
            return next(r['gid'] for r in records.values() if r['source'].endswith(path))
        try:
            proc=start()
            bridge.handle(root,dict(action='configure',max_concurrent='2',http_connections='4'))
            gid=add('/redirect')
            deadline=time.monotonic()+20
            while int(bridge.rpc(root,'tellStatus',[gid]).get('completedLength',0))<2*1024**2:
                assert time.monotonic()<deadline;time.sleep(.1)
            bridge.handle(root,dict(action='pause',backend='bt',id=gid))
            paused=bridge.rpc(root,'tellStatus',[gid]);done=int(paused['completedLength']);assert done>0
            shown=next(t for t in bridge.snapshot(root)['tasks'] if t['id']==gid)
            assert shown['transferProtocol']=='http' and shown['size']==LARGE and shown['completedBytes']==done
            assert shown['sources']=='' and shown['status']=='paused'
            bridge.handle(root,dict(action='stop',backend='bt'));proc.wait(timeout=10)
            proc=start();assert bridge.rpc(root,'tellStatus',[gid])['status']=='paused'
            slow=False;bridge.handle(root,dict(action='resume',backend='bt',id=gid))
            value=wait_status(root,gid,{'complete'},180);path=Path(value['files'][0]['path'])
            assert path.stat().st_size==LARGE and file_hash(path)==expected_hash(LARGE)
            assert any(p=='/large' and offset>0 for p,offset in requests)
            print(f'PASS: {LARGE} byte HTTP redirect download; pause/resume, restart and full SHA-256 verified.',flush=True)
            bridge.handle(root,dict(action='remove',backend='bt',id=gid));assert path.is_file()
            path.unlink()  # Generated fixture only; free the >2 GiB before other cases.
            deny=True;retry=add('/retry');wait_status(root,retry,{'error'})
            shown=next(t for t in bridge.snapshot(root)['tasks'] if t['id']==retry);assert shown['transferProtocol']=='http'
            deny=False;bridge.handle(root,dict(action='retry',backend='bt',id=retry))
            retry=next(r['gid'] for r in bridge.read_json(root/'gui/http-downloads.json',{}).values() if r['source'].endswith('/retry'))
            val=wait_status(root,retry,{'complete'});assert file_hash(Path(val['files'][0]['path']))==expected_hash(SMALL)
            print('PASS: failed HTTP task can retry without being treated as a magnet.',flush=True)
            slow=True;gid=add('/no-range')
            deadline=time.monotonic()+15
            while int(bridge.rpc(root,'tellStatus',[gid]).get('completedLength',0))<1024**2:
                assert time.monotonic()<deadline;time.sleep(.05)
            bridge.handle(root,dict(action='pause',backend='bt',id=gid));val=bridge.rpc(root,'tellStatus',[gid]);partial=Path(val['files'][0]['path']);before=partial.read_bytes()
            bridge.handle(root,dict(action='resume',backend='bt',id=gid));wait_status(root,gid,{'error'})
            assert partial.read_bytes()==before
            print('PASS: server without Range support does not truncate or replace partial data.',flush=True)
            bridge.handle(root,dict(action='configure',max_concurrent='2',http_connections='4'))
            gids=[add('/parallel-a'),add('/parallel-b')]
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                values=[bridge.rpc(root,'tellStatus',[g]) for g in gids]
                if all(v['status']=='active' and int(v['completedLength'])>0 for v in values):break
                time.sleep(.03)
            else:raise AssertionError('Two files were not downloading concurrently')
            for g in gids:
                value=wait_status(root,g,{'complete'})
                assert file_hash(Path(value['files'][0]['path']))==expected_hash(64*1024**2)
            assert peak.get('/parallel-a',0)>=2 and peak.get('/parallel-b',0)>=2, peak
            print('PASS: two concurrent files, each using multiple overlapping HTTP connections; SHA-256 verified.',flush=True)
            print('Peak connections:',{p:peak[p] for p in ['/parallel-a','/parallel-b']},flush=True)
        finally:
            if proc and proc.poll() is None:
                try:bridge.rpc(root,'shutdown');proc.wait(timeout=10)
                except Exception:proc.terminate();proc.wait(timeout=10)
            server.shutdown();server.server_close()
    print('HTTP_INTEGRATION_PASS',flush=True)

if __name__=='__main__':main()
