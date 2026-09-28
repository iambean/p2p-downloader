#!/usr/bin/env python3
"""Install a user-local command without pip, sudo or shell-profile edits."""
import os
from pathlib import Path
import sys

source = Path(__file__).resolve().parent / 'p2p'
target = Path.home() / '.local/bin/p2p'
source.chmod(source.stat().st_mode | 0o111)
target.parent.mkdir(parents=True, exist_ok=True)
if target.is_symlink() and target.resolve() == source:
    print(f'已安装：{target}')
elif target.exists() or target.is_symlink():
    print(f'安装失败：{target} 已存在，未覆盖。', file=sys.stderr)
    sys.exit(1)
else:
    target.symlink_to(source)
    print(f'已安装：{target} → {source}')
if str(target.parent) not in os.environ.get('PATH', '').split(os.pathsep):
    print('请将 ~/.local/bin 加入 PATH，或使用上面的完整路径运行。')
