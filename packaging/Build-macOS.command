#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

python3 -m pip install -r requirements.txt pyinstaller
RELEASE="$PROJECT_DIR/Releases/macOS"
WORK="$RELEASE/work"
DIST="$RELEASE/dist"
SPEC="$RELEASE/spec"
rm -rf "$WORK" "$DIST" "$SPEC"
mkdir -p "$RELEASE"

ICONSET="$RELEASE/VectorNaso.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -s format png -z "$size" "$size" "$PROJECT_DIR/assets/branding/VectorNaso_Icona.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  if [ "$size" -le 256 ]; then
    double=$((size * 2))
    sips -s format png -z "$double" "$double" "$PROJECT_DIR/assets/branding/VectorNaso_Icona.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  fi
done
iconutil -c icns "$ICONSET" -o "$RELEASE/VectorNaso.icns"

python3 -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name VectorNaso --icon "$RELEASE/VectorNaso.icns" \
  --distpath "$DIST" --workpath "$WORK" --specpath "$SPEC" \
  --add-data "$PROJECT_DIR/index.html:." \
  --add-data "$PROJECT_DIR/editor.js:." \
  --add-data "$PROJECT_DIR/enhancements.js:." \
  --add-data "$PROJECT_DIR/assets:assets" \
  --add-data "$PROJECT_DIR/Samples:Samples" \
  --collect-all vtracer --collect-all ezdxf --collect-all svgpathtools \
  --collect-all svglib --collect-all reportlab \
  "$PROJECT_DIR/vectornaso_server.py"

APP="$DIST/VectorNaso.app"
mkdir -p "$APP/Contents/Resources"
cp -R "$PROJECT_DIR/Samples" "$APP/Contents/Resources/Samples"
cp "$PROJECT_DIR/LEGGIMI.txt" "$APP/Contents/Resources/LEGGIMI.txt"
mkdir -p "$RELEASE/dmg-root"
rm -rf "$RELEASE/dmg-root/VectorNaso.app" "$RELEASE/dmg-root/Samples" "$RELEASE/dmg-root/Applicazioni"
cp -R "$APP" "$RELEASE/dmg-root/VectorNaso.app"
cp -R "$PROJECT_DIR/Samples" "$RELEASE/dmg-root/Samples"
ln -s /Applications "$RELEASE/dmg-root/Applicazioni"
hdiutil create -volname "VectorNaso" -srcfolder "$RELEASE/dmg-root" -ov -format UDZO "$RELEASE/VectorNaso-macOS.dmg"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$RELEASE/VectorNaso-macOS.zip"
echo "Build macOS completata: $RELEASE/VectorNaso-macOS.dmg"
