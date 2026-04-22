#!/usr/bin/env bash
# make_reverse_video.sh — produce Assets/Video/how_to_train_your_nailong_reverse.mp4.
#
# Reverses the full source clip and re-encodes to H.264 (libx264) with audio
# stripped. We reverse the whole file rather than just the stare segment so
# tweaking stare_start_ms / stare_end_ms in video_segments.json does not
# require regenerating this asset — VideoController computes the reverse-time
# offset as (duration_ms - t).
#
# Usage:
#   ./tools/make_reverse_video.sh                     # default in/out
#   ./tools/make_reverse_video.sh in.mp4 out.mp4
#
# ffmpeg lookup order:
#   1) $FFMPEG env var
#   2) `ffmpeg` on PATH
#   3) imageio-ffmpeg's bundled binary (pip install imageio-ffmpeg)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
IN="${1:-$REPO/Assets/Video/how_to_train_your_nailong.mp4}"
OUT="${2:-$REPO/Assets/Video/how_to_train_your_nailong_reverse.mp4}"

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

echo "[ffmpeg] $FF"
echo "[in   ]  $IN"
echo "[out  ]  $OUT"

"$FF" -y -hide_banner -loglevel warning \
    -i "$IN" \
    -vf reverse \
    -an \
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
    -movflags +faststart \
    "$OUT"

echo "[done ]  $(stat -c '%s bytes' "$OUT")"
