#!/usr/bin/env bash
# Build Mtrini Workspace for Linux (x86_64) and package it as .tar.gz, .deb and AppImage.
# Run from the repo root on Ubuntu 22.04 or newer (CI uses ubuntu-22.04 so the result runs on older glibc too).
# Needs: python3.12, node 20, dpkg-deb, and network access to download appimagetool.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import re; print(re.search(r'__version__ = \"(.+?)\"', open('backend/mtrini/__init__.py').read()).group(1))")
NAME=MtriniWorkspace
OUT=installer
mkdir -p "$OUT"

echo "== 1/5 frontend =="
npm ci --prefix frontend
npm run build --prefix frontend

echo "== 2/5 app bundle =="
python3 -m pip install --quiet -r backend/requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --clean --name "$NAME" \
  --add-data "frontend/dist:frontend/dist" --add-data "assets/logo-256.png:assets" \
  --collect-submodules mtrini \
  --exclude-module torch --exclude-module torchvision --exclude-module transformers \
  --exclude-module tensorflow --exclude-module pandas --exclude-module pyarrow \
  --exclude-module pytest --exclude-module matplotlib --exclude-module webview \
  backend/desktop.py

echo "== 3/5 smoke test =="
MTRINI_HEADLESS=1 MTRINI_HOME=$(mktemp -d) "dist/$NAME/$NAME" >/tmp/mtrini-smoke.log 2>&1 &
PID=$!
ok=0
for _ in $(seq 1 40); do
  if curl -fs http://127.0.0.1:8787/api/health; then ok=1; echo; break; fi
  sleep 2
done
kill "$PID" 2>/dev/null || true
if [ "$ok" != 1 ]; then echo "Smoke test failed:"; tail -50 /tmp/mtrini-smoke.log; exit 1; fi

echo "== 4/5 .tar.gz and .deb =="
tar -C dist -czf "$OUT/$NAME-$VERSION-linux-x86_64.tar.gz" "$NAME"

DEB=$(mktemp -d)/mtrini-workspace
mkdir -p "$DEB/DEBIAN" "$DEB/opt" "$DEB/usr/bin" "$DEB/usr/share/applications" "$DEB/usr/share/icons/hicolor/256x256/apps"
cp -r "dist/$NAME" "$DEB/opt/mtrini-workspace"
ln -s /opt/mtrini-workspace/$NAME "$DEB/usr/bin/mtrini-workspace"
cp assets/logo-256.png "$DEB/usr/share/icons/hicolor/256x256/apps/mtrini-workspace.png"
cat > "$DEB/usr/share/applications/mtrini-workspace.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mtrini Workspace
Comment=AI coding workspace by Compiwer AI
Exec=mtrini-workspace
Icon=mtrini-workspace
Categories=Development;IDE;
Terminal=false
EOF
cat > "$DEB/DEBIAN/control" <<EOF
Package: mtrini-workspace
Version: $VERSION
Section: devel
Priority: optional
Architecture: amd64
Depends: xdg-utils
Recommends: chromium | google-chrome-stable | microsoft-edge-stable
Maintainer: Compiwer AI <contact.compiwerai@gmail.com>
Homepage: https://github.com/compiwerai/mtrini-workspace
Description: Mtrini Workspace, an AI coding workspace
 Local-first desktop workspace with a coding agent, editor, terminal and Git.
 Works with local models and many API providers, plus a free built-in model.
EOF
dpkg-deb --root-owner-group --build "$DEB" "$OUT/mtrini-workspace_${VERSION}_amd64.deb"

echo "== 5/5 AppImage =="
APPDIR=$(mktemp -d)/$NAME.AppDir
mkdir -p "$APPDIR/usr/bin"
cp -r "dist/$NAME/." "$APPDIR/usr/bin/"
cp assets/logo-256.png "$APPDIR/mtrini-workspace.png"
sed 's/^Exec=.*/Exec=MtriniWorkspace/' "$DEB/usr/share/applications/mtrini-workspace.desktop" > "$APPDIR/mtrini-workspace.desktop"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/MtriniWorkspace" "$@"
EOF
chmod +x "$APPDIR/AppRun"
TOOL=$(mktemp -d)/appimagetool
curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT/$NAME-$VERSION-x86_64.AppImage"

(cd "$OUT" && sha256sum "$NAME-$VERSION-linux-x86_64.tar.gz" "mtrini-workspace_${VERSION}_amd64.deb" \
  "$NAME-$VERSION-x86_64.AppImage" > "$NAME-$VERSION-linux.sha256")
ls -la "$OUT"
