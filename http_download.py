"""Bounded HTTP metadata probes and conservative large-file transfer options."""
from email.message import Message
import hashlib
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = 'Mora/0.5'


def normalize_url(source):
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('无效的 HTTP/HTTPS 下载地址。')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('下载地址端口无效。') from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('下载地址端口无效。')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('下载地址不能包含明文账号密码。')
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in source):
        raise ValueError('下载地址包含空白或控制字符，请复制完整链接。')
    host = parsed.hostname.encode('idna').decode()
    if ':' in host:
        host = '[' + host + ']'
    if port is not None:
        host += ':' + str(port)
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host,
        urllib.parse.quote(parsed.path or '/', safe='/%:@!$&\'()*+,;=-._~'),
        urllib.parse.quote(parsed.query, safe='%!$&\'()*+,;=:/?@-._~[]'), ''))


class FileRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never allow a file download to follow file:, ftp: or another scheme.
        newurl = normalize_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and req.get_method() == 'HEAD':
            redirected.method = 'HEAD'
        return redirected


def safe_name(value):
    if not value or value in ('.', '..') or any(c in value for c in '/\\') or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('服务器返回了不安全的文件名，未开始下载。')
    return value


def probe(source):
    """HEAD first; read at most 512 bytes if a server does not support HEAD."""
    source = normalize_url(source)
    opener = urllib.request.build_opener(FileRedirectHandler())
    for method in ('HEAD', 'GET'):
        headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}
        if method == 'GET':
            headers['Range'] = 'bytes=0-511'
        try:
            with opener.open(urllib.request.Request(source, headers=headers, method=method), timeout=20) as response:
                if response.status not in (200, 206):
                    raise RuntimeError('服务器未返回可下载的文件。')
                disposition = Message()
                disposition['Content-Disposition'] = response.headers.get('Content-Disposition', '')
                kind = response.headers.get_content_type()
                if kind in ('text/html', 'application/xhtml+xml') and disposition.get_content_disposition() != 'attachment':
                    raise RuntimeError('该地址返回网页或登录页面，请使用可直接下载文件的链接。')
                if method == 'GET':
                    response.read(512)
                raw_name = disposition.get_filename()
                if not raw_name:
                    raw_name = urllib.parse.unquote(urllib.parse.urlsplit(response.geturl()).path.rsplit('/', 1)[-1])
                name = safe_name(raw_name or 'download-' + hashlib.sha256(source.encode()).hexdigest()[:12])
                length = response.headers.get('Content-Length', '')
                match = re.fullmatch(r'bytes \d+-\d+/(\d+)', response.headers.get('Content-Range', ''))
                size = int(match[1]) if match else int(length) if response.status == 200 and length.isdigit() else 0
                return dict(name=name, size=size, etag=response.headers.get('ETag'),
                            modified=response.headers.get('Last-Modified'), content_type=kind,
                            accepts_ranges=True if response.status == 206 or response.headers.get('Accept-Ranges') == 'bytes' else False if response.headers.get('Accept-Ranges') == 'none' else None)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if method == 'HEAD' and code in (403, 405, 501):
                continue
            if code in (401, 403):
                raise RuntimeError('下载链接需要登录或已经过期，请从浏览器获取新的直链。') from None
            if code == 404:
                raise RuntimeError('下载地址不存在或已失效（HTTP 404）。') from None
            raise RuntimeError(f'下载服务器返回错误，请稍后重试：HTTP {code}') from None
        except urllib.error.URLError:
            raise RuntimeError('无法连接下载服务器，请检查网络或稍后重试。') from None
    raise RuntimeError('无法获取下载文件信息。')


def options(name, connections=4):
    if connections not in (1, 2, 4, 8, 16):
        raise ValueError('单文件连接数设置无效。')
    return {'out': safe_name(name), 'continue': 'true', 'always-resume': 'true',
            'allow-overwrite': 'false', 'auto-file-renaming': 'false',
            'file-allocation': 'none', 'split': str(connections), 'max-connection-per-server': str(connections),
            'min-split-size': '8M',
            'max-tries': '8', 'retry-wait': '5', 'connect-timeout': '15', 'timeout': '30',
            'follow-torrent': 'false', 'follow-metalink': 'false',
            'http-accept-gzip': 'false', 'user-agent': USER_AGENT}
