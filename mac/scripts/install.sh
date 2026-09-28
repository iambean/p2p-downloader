#!/bin/zsh
set -euo pipefail
project_root=${0:A:h:h}
source_app="$project_root/dist/P2P Downloads.app"
target_app="/Applications/P2P Downloads.app"
if [[ ! -d "$source_app" ]]; then
  echo "请先运行 scripts/build.sh" >&2
  exit 1
fi
if [[ -e "$target_app" ]]; then
  bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$target_app/Contents/Info.plist" 2>/dev/null || true)
  if [[ "$bundle_id" != "com.xinfan.p2p-downloads" ]]; then
    echo "目标已有其他同名应用，未覆盖。" >&2
    exit 1
  fi
  if pgrep -f '^/Applications/P2P Downloads.app/Contents/MacOS/P2PDownloads' >/dev/null; then
    echo "请先退出 P2P Downloads 界面，再更新；后台下载不受影响。" >&2
    exit 1
  fi
  backup="$project_root/.build/app-backup-$(date +%Y%m%d-%H%M%S).app"
  mv "$target_app" "$backup"
fi
ditto "$source_app" "$target_app"
codesign --verify --strict "$target_app"
echo "$target_app"
