#!/usr/bin/env python3
"""
probe_segments.py — Inspect Naiwa.mp4 and produce/update Assets/Config/video_segments.json.

Two modes:

  Probe (read-only): print fps / duration / frame count.
      python3 tools/probe_segments.py --probe

  Write: set or override segment timestamps.
      python3 tools/probe_segments.py \
          --stare-start-ms 0 \
          --stare-end-ms 1000 \
          --laugh-trigger-ms 1000

Times accept either milliseconds via --*-ms or seconds via --*-s; integer or float.
The script preserves any existing _comment / _field_doc keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = REPO_ROOT / "Assets" / "Video" / "Naiwa.mp4"
DEFAULT_CONFIG = REPO_ROOT / "Assets" / "Config" / "video_segments.json"


def probe(video: Path) -> dict:
    """Return {fps, duration_ms, frame_count, width, height} via cv2."""
    try:
        import cv2  # type: ignore
    except ImportError:
        sys.exit("opencv-python not installed: pip install opencv-python")

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"failed to open {video}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()

    duration_ms = int(round(frame_count / fps * 1000.0)) if fps > 0 else None
    return {
        "fps": round(fps, 4),
        "duration_ms": duration_ms,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def to_ms(ms: float | None, s: float | None) -> int | None:
    if ms is not None:
        return int(round(ms))
    if s is not None:
        return int(round(s * 1000.0))
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--probe", action="store_true", help="probe only, do not modify config")

    g_stare = ap.add_argument_group("segment timestamps")
    g_stare.add_argument("--stare-start-ms", type=float)
    g_stare.add_argument("--stare-start-s", type=float)
    g_stare.add_argument("--stare-end-ms", type=float)
    g_stare.add_argument("--stare-end-s", type=float)
    g_stare.add_argument("--laugh-trigger-ms", type=float)
    g_stare.add_argument("--laugh-trigger-s", type=float)
    g_stare.add_argument("--laugh-end-ms", type=float)
    g_stare.add_argument("--laugh-end-s", type=float)

    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"video not found: {args.video}")

    info = probe(args.video)
    print(f"[probe] {args.video.name}")
    for k, v in info.items():
        print(f"  {k:13s} {v}")

    if args.probe:
        return

    cfg = load_config(args.config)
    cfg.setdefault("source", "ms-appx:///Assets/Video/Naiwa.mp4")
    cfg.setdefault("reverse_source", "ms-appx:///Assets/Video/Naiwa_reverse.mp4")
    cfg["fps"] = info["fps"]
    cfg["duration_ms"] = info["duration_ms"]
    cfg["frame_count"] = info["frame_count"]

    overrides = {
        "stare_start_ms": to_ms(args.stare_start_ms, args.stare_start_s),
        "stare_end_ms": to_ms(args.stare_end_ms, args.stare_end_s),
        "laugh_trigger_frame_ms": to_ms(args.laugh_trigger_ms, args.laugh_trigger_s),
        "laugh_segment_end_ms": to_ms(args.laugh_end_ms, args.laugh_end_s),
    }
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v

    save_config(args.config, cfg)
    print(f"[write] {args.config.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
