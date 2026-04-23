#!/usr/bin/env bash
# make_reverse_video.sh — produce Assets/Video/how_to_train_your_nailong_reverse.mp4.
#
# Reverses ONLY the stare segment ([stare_start_ms, stare_end_ms]) of the
# source clip and re-encodes to H.264 with audio stripped. We deliberately
# do NOT reverse the whole 15.4s file: when MediaPlayer first switches to
# the reverse source, the very first frames slip onto the screen before
# the seek lands. If reverse contains the whole clip, those leaked frames
# are the END of the laugh segment (visible silent flash). By making the
# reverse asset only the stare segment, any leaked frames are still the
# correct stare-loop content, and EnterReverse() can play from t=0
# without any seek arithmetic.
#
# Default cut: stare_start_ms=0, stare_end_ms=1000 (matches video_segments.json).
# Override with --stare-start-ms / --stare-end-ms in milliseconds.
#
# Usage:
#   ./tools/make_reverse_video.sh
#   ./tools/make_reverse_video.sh --stare-start-ms 0 --stare-end-ms 1000
#   ./tools/make_reverse_video.sh --in foo.mp4 --out bar.mp4
#
# ffmpeg lookup order:
#   1) $FFMPEG env var
#   2) `ffmpeg` on PATH
#   3) imageio-ffmpeg's bundled binary (pip install imageio-ffmpeg)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
IN="$REPO/Assets/Video/how_to_train_your_nailong.mp4"
OUT="$REPO/Assets/Video/how_to_train_your_nailong_reverse.mp4"
STARE_START_MS=0
STARE_END_MS=1000
FPS=30

while [[ $# -gt 0 ]]; do
    case "$1" in
        --in)             IN="$2"; shift 2 ;;
        --out)            OUT="$2"; shift 2 ;;
        --stare-start-ms) STARE_START_MS="$2"; shift 2 ;;
        --stare-end-ms)   STARE_END_MS="$2"; shift 2 ;;
        --fps)            FPS="$2"; shift 2 ;;
        -h|--help)        sed -n '2,/^$/p' "$0"; exit 0 ;;
        *)                echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if (( STARE_END_MS <= STARE_START_MS )); then
    echo "stare_end_ms ($STARE_END_MS) must be > stare_start_ms ($STARE_START_MS)" >&2
    exit 2
fi

if [[ -n "${FFMPEG:-}" ]]; then
    FF="$FFMPEG"
elif command -v ffmpeg >/dev/null 2>&1; then
    FF="ffmpeg"
else
    FF="$(python3 -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
    if [[ -z "$FF" || ! -x "$FF" ]]; then
        echo "no ffmpeg found. install: pip install --user imageio-ffmpeg" >&2
        exit 1
    fi
fi

# ffmpeg wants seconds with decimals.
SS=$(awk "BEGIN { printf \"%.3f\", $STARE_START_MS / 1000.0 }")
DUR=$(awk "BEGIN { printf \"%.3f\", ($STARE_END_MS - $STARE_START_MS) / 1000.0 }")
END=$(awk "BEGIN { printf \"%.3f\", $STARE_END_MS / 1000.0 }")

echo "[ffmpeg] $FF"
echo "[in   ]  $IN"
echo "[out  ]  $OUT"
echo "[clip ]  ss=${SS}s  duration=${DUR}s  (stare ${STARE_START_MS}–${STARE_END_MS} ms)"
echo "[fps  ]  ${FPS}"

# IMPORTANT: trim MUST happen inside the filtergraph before reverse.
# Using output-side `-ss/-t` with `-vf reverse` reverses the whole source first
# and only then keeps the first second of the reversed output, which produces
# the END of the original clip (late laugh / lying-down frames) instead of the
# stare segment. `trim + setpts + reverse` preserves the intended cut order.
# -an strips audio (reversed audio sounds wrong anyway).
"$FF" -y -hide_banner -loglevel warning \
    -i "$IN" \
    -vf "trim=start=${SS}:end=${END},setpts=PTS-STARTPTS,fps=${FPS},reverse" \
    -an \
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
    -movflags +faststart \
    "$OUT"

echo "[done ]  $(stat -c '%s bytes' "$OUT")"
