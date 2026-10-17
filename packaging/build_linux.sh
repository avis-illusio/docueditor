#!/usr/bin/env bash
# Build the Linux release artifacts:
#   docueditor-<version>-x86_64              (single-file ELF executable)
#   docueditor-<version>-x86_64.AppImage
#   docueditor_<version>_amd64.deb
#   docueditor-<version>-1.x86_64.rpm
#   docueditor-<version>-1-x86_64.pkg.tar.zst
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARCH="${ARCH:-x86_64}"
VERSION="${VERSION:-$(PYTHONPATH="$ROOT/src" python -c 'import docueditor; print(docueditor.__version__)')}"
NFPM_VERSION="${NFPM_VERSION:-2.48.0}"
echo "Building Docueditor ${VERSION} for ${ARCH}"

rm -rf build dist
mkdir -p dist build

echo "==> PyInstaller (onedir)"
DOCUEDITOR_ONEFILE=0 DOCUEDITOR_NAME=docueditor \
  pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/docueditor.spec

echo "==> PyInstaller (onefile)"
DOCUEDITOR_ONEFILE=1 DOCUEDITOR_NAME=docueditor-standalone \
  pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller-onefile packaging/docueditor.spec
mv dist/docueditor-standalone "dist/docueditor-${VERSION}-${ARCH}"

echo "==> AppDir"
APPDIR="$ROOT/build/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/docueditor/. "$APPDIR/usr/bin/"
cp packaging/docueditor.desktop "$APPDIR/docueditor.desktop"
cp packaging/icons/docueditor-256.png "$APPDIR/docueditor.png"
cp packaging/docueditor.desktop "$APPDIR/usr/share/applications/docueditor.desktop"
cp packaging/icons/docueditor-256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/docueditor.png"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
for lib in /usr/lib/libstdc++.so.6 /usr/lib64/libstdc++.so.6 \
           /usr/lib/x86_64-linux-gnu/libstdc++.so.6 \
           /usr/lib/aarch64-linux-gnu/libstdc++.so.6; do
    if [ -r "$lib" ] && grep -aq 'CXXABI_1.3.15' "$lib"; then
        LD_PRELOAD="$lib${LD_PRELOAD:+:$LD_PRELOAD}"
        export LD_PRELOAD
        break
    fi
done
exec "$HERE/usr/bin/docueditor" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "==> AppImage"
APPIMAGETOOL="$ROOT/build/appimagetool-${ARCH}.AppImage"
curl -fsSL -o "$APPIMAGETOOL" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
chmod +x "$APPIMAGETOOL"
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" \
  "dist/docueditor-${VERSION}-${ARCH}.AppImage"

echo "==> deb / rpm / Arch package (nfpm ${NFPM_VERSION})"
NFPM_ARCH="x86_64"
case "$ARCH" in
  aarch64|arm64) NFPM_ARCH="arm64" ;;
  x86_64|amd64) NFPM_ARCH="x86_64" ;;
esac
curl -fsSL "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/nfpm_${NFPM_VERSION}_Linux_${NFPM_ARCH}.tar.gz" \
  | tar -xz -C build nfpm
VERSION="$VERSION" build/nfpm package -f packaging/nfpm.yaml -p deb -t dist/
VERSION="$VERSION" build/nfpm package -f packaging/nfpm.yaml -p rpm -t dist/
VERSION="$VERSION" build/nfpm package -f packaging/nfpm.yaml -p archlinux -t dist/

echo "==> Artifacts"
ls -lh dist | grep -v '^total'
