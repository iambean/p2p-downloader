#!/bin/zsh
set -euo pipefail
project_root=${0:A:h:h}
source_app="$project_root/dist/Mora.app"
target_app="/Applications/Mora.app"
legacy_app="/Applications/P2P Downloads.app"
if [[ ! -d "$source_app" ]]; then
  echo "请先运行 scripts/build.sh" >&2
  exit 1
fi
codesign --verify --deep --strict "$source_app"
# Validate both names before replacing either; existing downloads are external.
for candidate in "$target_app" "$legacy_app"; do
  [[ -e "$candidate" ]] || continue
  bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$candidate/Contents/Info.plist" 2>/dev/null || true)
  if [[ "$bundle_id" != "com.xinfan.p2p-downloads" ]]; then
    echo "目标已有其他同名应用，未覆盖：$candidate" >&2
    exit 1
  fi
  if pgrep -f "^$candidate/Contents/MacOS/P2PDownloads" >/dev/null; then
    echo "请先退出 Mora / P2P Downloads 界面，再更新；后台下载不受影响。" >&2
    exit 1
  fi
done
mkdir -p "$project_root/.build"
for candidate in "$target_app" "$legacy_app"; do
  [[ -e "$candidate" ]] || continue
  backup="$project_root/.build/${candidate:t:r}-backup-$(date +%Y%m%d-%H%M%S).app"
  mv "$candidate" "$backup"
done
ditto "$source_app" "$target_app"
codesign --verify --deep --strict "$target_app"
echo "$target_app"
