"""File operations scoped to a download's authoritative engine file list."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import uuid


def checked_path(root, path, device=None):
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if not root.is_dir() or root == Path('/'):
        raise RuntimeError('下载目录不可用，未删除文件。')
    if device is not None and root.stat().st_dev != device:
        raise RuntimeError('下载目录所在磁盘发生变化，未删除文件。')
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise RuntimeError('文件不在该任务的下载目录内，拒绝删除。')
    if not relative.parts:
        raise RuntimeError('不能删除整个下载目录。')
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError('下载文件路径包含符号链接，拒绝删除。')
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise RuntimeError('文件清单包含目录或特殊文件，拒绝删除。')
    return path


def records_for(root, paths):
    root = Path(os.path.abspath(root))
    result = []
    for path in dict.fromkeys(str(p) for p in paths):
        path = checked_path(root, path)
        result.append({'root': str(root), 'path': str(path), 'device': root.stat().st_dev})
    return result


def bt_records(value):
    root = value.get('dir')
    files = value.get('files', [])
    if not files:
        return []
    if not root or not Path(root).is_absolute():
        raise RuntimeError('缺少可信的下载目录，未删除文件。')
    paths = []
    for file in files:
        raw = file.get('path', '')
        if not raw:
            continue  # Magnet metadata not resolved yet.
        if not Path(raw).is_absolute():
            raise RuntimeError('文件清单路径不完整，未删除文件。')
        paths += [raw, raw + '.aria2']
    name = value.get('bittorrent', {}).get('info', {}).get('name', '')
    if name and Path(name).name == name and name not in ('.', '..'):
        paths.append(str(Path(root) / (name + '.aria2')))
    return records_for(root, paths)


def trash_helper():
    candidates = [os.environ.get('P2P_FILE_HELPER'),
                  str(Path(__file__).resolve().parent.parent.parent / 'Helpers/P2PFileOps'),
                  str(Path(__file__).resolve().parent / 'mac/.build/arm64-apple-macosx/release/P2PFileOps'),
                  '/Applications/Mora.app/Contents/Helpers/P2PFileOps',
                  '/Applications/P2P Downloads.app/Contents/Helpers/P2PFileOps']
    for path in candidates:
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError('缺少废纸篓组件，文件已保留；请更新应用后重试。')


def trash_records(records):
    paths = []
    for record in records:
        path = checked_path(record['root'], record['path'], record['device'])
        if path.exists():
            paths.append(str(path))
    if not paths:
        return
    result = subprocess.run([trash_helper()], input=json.dumps({'paths': paths}),
                            capture_output=True, text=True, timeout=120)
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('文件清理组件未返回有效结果；请检查原目录后重试。')
    if result.returncode or response.get('errors'):
        raise RuntimeError('部分文件未能移到废纸篓：' + '; '.join(response.get('errors', [result.stderr.strip()])))
    # Remove only now-empty subdirectories; never recurse or remove the root.
    parents = set()
    for record in records:
        root = Path(record['root'])
        parent = Path(record['path']).parent
        while parent != root and parent.is_relative_to(root):
            parents.add(parent)
            parent = parent.parent
    for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        try:
            parent.rmdir()
        except OSError:
            pass  # Includes directories holding unrelated files.


def retain_partial(temp_dir, part_met, identifier, name):
    if not re.fullmatch(r'\d+\.part\.met', part_met):
        raise RuntimeError('无法识别此任务的临时文件，任务已保留。')
    root = Path(temp_dir).resolve()
    meta = checked_path(root, root / part_met)
    if not meta.is_file():
        raise RuntimeError('临时文件索引缺失，未取消下载。')
    data = checked_path(root, root / part_met.removesuffix('.met'))
    storage = root / '.p2p-retained'
    if storage.is_symlink():
        raise RuntimeError('恢复目录是符号链接，未取消下载。')
    backup = storage / (identifier + '-' + uuid.uuid4().hex[:10])
    backup.mkdir(parents=True, mode=0o700)
    for suffix in ('', '.bak', '.backup', '.seeds'):
        source = checked_path(root, Path(str(meta) + suffix))
        if source.is_file():
            shutil.copy2(source, backup / source.name)
    moved = False
    if data.is_file():
        try:
            # Preserve the open inode through aMule cancellation without copying GBs.
            os.link(data, backup / data.name)
        except OSError:
            # Same-volume rename also works on removable filesystems without hardlinks.
            # aMule closes its handle on cancel; missing old path is only a debug log.
            data.rename(backup / data.name)
            moved = True
    try:
        (backup / 'retained.json').write_text(json.dumps({'hash': identifier, 'name': name,
            'original_temp_dir': str(root), 'part_met': part_met, 'moved_data': moved}, ensure_ascii=False))
    except Exception:
        if moved and not data.exists():
            (backup / data.name).rename(data)
        raise
    return backup


def restore_retained_data(backup):
    """Undo a same-volume staging move if cancellation did not complete."""
    info = json.loads((backup / 'retained.json').read_text())
    if info.get('moved_data'):
        source = backup / info['part_met'].removesuffix('.met')
        original = Path(info['original_temp_dir']) / source.name
        if source.is_file() and not original.exists():
            source.rename(original)
