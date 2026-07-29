#!/data/data/com.termux/files/usr/bin/bash
# ==========================================================================
# EMO — fetch MediaPipe browser assets (one-time, on the phone)
# ==========================================================================
# The browser face runs MediaPipe Tasks (hand gesture + body pose) fully
# offline. That needs three things served locally by the face server:
#   1. vision_bundle.mjs        — the ES-module JS bundle
#   2. wasm/                    — the WASM runtime folder
#   3. *.task                   — the gesture + pose model bundles
#
# We PIN an exact version — never @latest — because the CDN wasm/ folder
# layout has broken across releases. Run this ONCE on the phone after syncing:
#     bash face/static/vendor/fetch_mediapipe.sh
# It downloads into face/static/vendor/mediapipe/ (git-ignored — these are
# large binaries that don't need to live in the laptop copy; re-run after a
# fresh sync if the folder was wiped).
#
# Needs: curl (pkg install curl). ~15-30 MB total.
# ==========================================================================
set -e
cd "$(dirname "$0")"

VER="0.10.20"                                  # pinned @mediapipe/tasks-vision version
JSDELIVR="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VER}"
GSTORAGE="https://storage.googleapis.com/mediapipe-models"
OUT="mediapipe"
WASM="$OUT/wasm"

mkdir -p "$WASM"

echo "[fetch] MediaPipe tasks-vision @${VER}"

# 1. ES-module bundle
curl -fL -o "$OUT/vision_bundle.mjs" "$JSDELIVR/vision_bundle.mjs"

# 2. WASM runtime (the loader picks the right one; grab both simd + non-simd
#    plus their .js glue so any device works).
for f in \
    vision_wasm_internal.js  vision_wasm_internal.wasm \
    vision_wasm_nosimd_internal.js  vision_wasm_nosimd_internal.wasm
do
    curl -fL -o "$WASM/$f" "$JSDELIVR/wasm/$f" || \
        echo "[fetch] NOTE: $f not in this release (ok if a variant is missing)."
done

# 3. Model bundles (float16 = smaller/faster on mobile).
curl -fL -o "$OUT/gesture_recognizer.task" \
    "$GSTORAGE/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
curl -fL -o "$OUT/pose_landmarker_lite.task" \
    "$GSTORAGE/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"

echo "[fetch] done -> $(pwd)/$OUT"
echo "[fetch] verify: ls -la $OUT $WASM"
echo "[fetch] If a URL 404s, open https://www.jsdelivr.com/package/npm/@mediapipe/tasks-vision"
echo "        and confirm the version/paths, then re-run."
