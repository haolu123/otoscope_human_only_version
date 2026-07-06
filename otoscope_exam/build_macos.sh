#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Otoscope Exam"
DIST_ROOT="dist_macos"
RELEASE_ROOT="${DIST_ROOT}/otoscope_exam_mac"

copy_ffmpeg_runtime() {
  local ffmpeg_exe="$1"
  local release_root="$2"
  local release_ffmpeg_dir="$release_root/ffmpeg"
  local release_lib_dir="$release_root/lib"
  mkdir -p "$release_ffmpeg_dir" "$release_lib_dir"
  cp "$ffmpeg_exe" "$release_ffmpeg_dir/ffmpeg"

  python - "$ffmpeg_exe" "$release_lib_dir" <<'PY'
import os
import shutil
import subprocess
import sys
from pathlib import Path

ffmpeg = Path(sys.argv[1]).resolve()
release_lib = Path(sys.argv[2]).resolve()
conda_prefix = Path(os.environ.get("CONDA_PREFIX", "")).resolve()
queue = [ffmpeg]
seen = set()

def conda_dependency(line: str) -> Path | None:
    line = line.strip()
    if not line or line.endswith(":"):
        return None
    dep = line.split(" ", 1)[0]
    if dep.startswith("@rpath/"):
        path = conda_prefix / "lib" / dep.removeprefix("@rpath/")
        if path.suffix == ".dylib":
            return path
    if not dep.startswith(str(conda_prefix)):
        return None
    path = Path(dep)
    if path.suffix != ".dylib":
        return None
    return path

while queue:
    binary = queue.pop()
    try:
        output = subprocess.check_output(["otool", "-L", str(binary)], text=True)
    except Exception as exc:
        print(f"warning: could not inspect {binary}: {exc}", file=sys.stderr)
        continue
    for line in output.splitlines()[1:]:
        dep = conda_dependency(line)
        if dep is None or dep in seen or not dep.exists():
            continue
        seen.add(dep)
        target = release_lib / dep.name
        if not target.exists():
            shutil.copy2(dep, target)
        queue.append(dep)

print(f"Copied {len(seen)} ffmpeg dylib dependencies to {release_lib}")
PY
}

verify_source_ffmpeg() {
  local ffmpeg_exe="$1"
  echo "imageio_ffmpeg executable: $ffmpeg_exe"
  echo "Source ffmpeg linked libraries:"
  otool -L "$ffmpeg_exe"
  if otool -L "$ffmpeg_exe" | grep -qi "SDL3"; then
    echo "Refusing to bundle ffmpeg because it depends on SDL3." >&2
    exit 1
  fi
}

verify_bundled_ffmpeg() {
  local release_root="$1"
  local bundled_ffmpeg="$release_root/ffmpeg/ffmpeg"
  echo "Bundled ffmpeg version check:"
  "$bundled_ffmpeg" -hide_banner -version

  local sample_video
  sample_video="$(
    find "$release_root/videos" -type f \( -iname "*.mov" -o -iname "*.mp4" -o -iname "*.avi" -o -iname "*.m4v" \) 2>/dev/null | head -n 1 || true
  )"
  if [ -n "$sample_video" ]; then
    echo "Bundled ffmpeg video smoke test: $sample_video"
    "$bundled_ffmpeg" -hide_banner -i "$sample_video" -f null -
  else
    echo "No bundled sample video found; skipping ffmpeg video smoke test."
  fi
}

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
verify_source_ffmpeg "$FFMPEG_EXE"
copy_ffmpeg_runtime "$FFMPEG_EXE" "$RELEASE_ROOT"
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
chmod +x "${RELEASE_ROOT}"/lib/*.dylib 2>/dev/null || true
verify_bundled_ffmpeg "$RELEASE_ROOT"

ditto -c -k --keepParent "${RELEASE_ROOT}" "${DIST_ROOT}/otoscope_exam_mac.zip"
echo "Build complete: ${DIST_ROOT}/otoscope_exam_mac.zip"
