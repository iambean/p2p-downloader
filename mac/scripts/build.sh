#!/bin/zsh
set -euo pipefail
project_root=${0:A:h:h}
cd "$project_root"
swift build -c release --arch arm64
release_bin=$(swift build -c release --arch arm64 --show-bin-path)
app="$project_root/dist/Mora.app"
signing_identity=${P2P_SIGNING_IDENTITY:--}
sign_flags=(--force --sign "$signing_identity")
if [[ "$signing_identity" != "-" ]]; then
  sign_flags+=(--options runtime --timestamp)
fi
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/p2p" "$app/Contents/Helpers" "$app/Contents/Frameworks"
cp "$release_bin/P2PDownloads" "$app/Contents/MacOS/P2PDownloads"
install_name_tool -add_rpath '@executable_path/../Frameworks' "$app/Contents/MacOS/P2PDownloads"
ditto "$release_bin/Sparkle.framework" "$app/Contents/Frameworks/Sparkle.framework"
codesign "${sign_flags[@]}" --deep "$app/Contents/Frameworks/Sparkle.framework"
cp "$release_bin/P2PFileOps" "$app/Contents/Helpers/P2PFileOps"
codesign "${sign_flags[@]}" "$app/Contents/Helpers/P2PFileOps"
cp Resources/Info.plist "$app/Contents/Info.plist"
for module in engine.py cli.py gui_bridge.py file_actions.py install_amule.py; do
  cp "$project_root/../$module" "$app/Contents/Resources/p2p/"
done
ditto "$project_root/../locales" "$app/Contents/Resources/locales"
iconset="$project_root/.build/AppIcon.iconset"
mkdir -p "$iconset"
xcrun swift scripts/MakeIcon.swift "$project_root/.build/AppIcon.png"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$project_root/.build/AppIcon.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$project_root/.build/AppIcon.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/AppIcon.icns"
cp "$project_root/../THIRD_PARTY_NOTICES.md" "$app/Contents/Resources/"
install -m 644 "$project_root/.build/checkouts/Sparkle/LICENSE" "$app/Contents/Resources/SPARKLE-LICENSE.txt"
codesign "${sign_flags[@]}" "$app"
codesign --verify --deep --strict "$app"
echo "$app"
