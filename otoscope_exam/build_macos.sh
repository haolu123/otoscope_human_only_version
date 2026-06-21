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
  app.py

mkdir -p "${RELEASE_ROOT}/result"
cp -R "dist/${APP_NAME}.app" "${RELEASE_ROOT}/"
cp "INSTRUCTIONS.txt" "${RELEASE_ROOT}/"
cp "READ_ME_FIRST_MAC.txt" "${RELEASE_ROOT}/"

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

ditto -c -k --keepParent "${RELEASE_ROOT}" "${DIST_ROOT}/otoscope_exam_mac.zip"
echo "Build complete: ${DIST_ROOT}/otoscope_exam_mac.zip"

