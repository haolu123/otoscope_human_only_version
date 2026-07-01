#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Otoscope Exam"
DIST_ROOT="dist_macos"
RELEASE_ROOT="${DIST_ROOT}/otoscope_exam_mac"

rm -rf build dist "${DIST_ROOT}" "${APP_NAME}.spec"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "${APP_NAME}" \
  --copy-metadata imageio \
  --copy-metadata imageio-ffmpeg \
  --collect-data imageio_ffmpeg \
  --collect-binaries imageio_ffmpeg \
  --hidden-import imageio.plugins.ffmpeg \
  --hidden-import imageio_ffmpeg \
  app.py

mkdir -p "${RELEASE_ROOT}/result"
cp -R "dist/${APP_NAME}.app" "${RELEASE_ROOT}/"
mkdir -p "${RELEASE_ROOT}/ffmpeg"
FFMPEG_EXE="$(
python - <<'PY'
import shutil
try:
    import imageio_ffmpeg
    print(imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    print(shutil.which("ffmpeg") or "")
PY
)"
if [ -z "$FFMPEG_EXE" ] || [ ! -f "$FFMPEG_EXE" ]; then
  echo "Could not locate ffmpeg executable for bundling" >&2
  exit 1
fi
cp "$FFMPEG_EXE" "${RELEASE_ROOT}/ffmpeg/ffmpeg"
cp "INSTRUCTIONS.txt" "${RELEASE_ROOT}/"
cp "READ_ME_FIRST_MAC.txt" "${RELEASE_ROOT}/"
cp "fixed_questions_100.json" "${RELEASE_ROOT}/"

if [ -d "videos" ]; then
  cp -R "videos" "${RELEASE_ROOT}/videos"
else
  mkdir -p "${RELEASE_ROOT}/videos"
  cat > "${RELEASE_ROOT}/videos/PUT_VIDEOS_HERE.txt" <<'EOF'
Copy the full videos folder here before running the app.

Expected category folders:
AOM
Effusion
Normal
Perforation
Retraction
Tubes
Tympanosclerosis
EOF
fi

chmod +x "${RELEASE_ROOT}/${APP_NAME}.app/Contents/MacOS/${APP_NAME}" || true
chmod +x "${RELEASE_ROOT}/ffmpeg/ffmpeg" || true

ditto -c -k --keepParent "${RELEASE_ROOT}" "${DIST_ROOT}/otoscope_exam_mac.zip"
echo "Build complete: ${DIST_ROOT}/otoscope_exam_mac.zip"
