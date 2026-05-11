#!/usr/bin/env python3
"""
Nailong Desktop Pet — Asset Preparation

Extracts video frames, removes backgrounds with rembg, produces transparent
PNG sprite frames, extracts audio tracks, and copies config files.

Usage:
    python prepare_assets.py                   # full pipeline
    python prepare_assets.py --no-rembg        # skip bg removal (quick test)
    python prepare_assets.py --height 300      # taller pet

Prerequisites:
    pip install --user Pillow rembg imageio-ffmpeg
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"


# ── helpers ────────────────────────────────────────────────────────


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except ImportError:
        sys.exit("ERROR: ffmpeg not found. Run: pip install --user imageio-ffmpeg")


def find_ffprobe() -> str | None:
    """Find ffprobe (optional — used to auto-detect video duration)."""
    path = shutil.which("ffprobe")
    if path:
        return path
    # imageio-ffmpeg bundles ffmpeg but not ffprobe; try sibling path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        ffmpeg = Path(get_ffmpeg_exe())
        candidate = ffmpeg.parent / ffmpeg.name.replace("ffmpeg", "ffprobe")
        if candidate.exists():
            return str(candidate)
    except ImportError:
        pass
    return None


def get_video_duration(ffmpeg: str, video: Path) -> float | None:
    """Get video duration in seconds using ffmpeg."""
    try:
        result = subprocess.run(
            [
                ffmpeg, "-i", str(video),
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=30,
        )
        # Parse duration from stderr (ffmpeg prints info to stderr)
        for line in result.stderr.splitlines():
            if "Duration:" in line:
                # Format: Duration: HH:MM:SS.ss
                part = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = part.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass

    # Fallback: try ffprobe
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video),
                ],
                capture_output=True, text=True, timeout=15,
            )
            return float(result.stdout.strip())
        except Exception:
            pass
    return None


def extract_frames(
    ffmpeg: str, video: Path, out_dir: Path,
    start_s: float, end_s: float, fps: int,
) -> list[Path]:
    """Extract a segment of video as individual PNGs."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "warning",
            "-ss", f"{start_s:.3f}",
            "-t", f"{end_s - start_s:.3f}",
            "-i", str(video),
            "-vf", f"fps={fps}",
            str(out_dir / "%04d.png"),
        ],
        check=True,
    )
    return sorted(out_dir.glob("*.png"))


def extract_audio(
    ffmpeg: str, video: Path, out_path: Path,
    start_s: float, end_s: float | None = None,
) -> bool:
    """Extract audio segment as WAV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-loglevel", "warning",
        "-i", str(video),
        "-ss", f"{start_s:.3f}",
    ]
    if end_s is not None:
        cmd += ["-t", f"{end_s - start_s:.3f}"]
    cmd += [
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def clamp_alpha(img):
    """Post-process alpha: push near-opaque pixels to fully opaque.

    rembg often produces alpha ~230 for the character body instead of 255,
    making the sprite look slightly transparent.  This remaps alpha so that
    values above a threshold become 255 while keeping soft edges intact.
    """
    import numpy as np

    arr = np.array(img)
    a = arr[:, :, 3].astype(np.float32)
    threshold = 180
    a = np.where(a > threshold, 255, a * 255 / threshold)
    arr[:, :, 3] = np.clip(a, 0, 255).astype(np.uint8)
    from PIL import Image

    return Image.fromarray(arr, "RGBA")


def process_frames(frames: list[Path], height: int, use_rembg: bool):
    """Resize, remove background, and fix alpha for each frame."""
    from PIL import Image

    rembg_fn = None
    if use_rembg:
        from rembg import remove

        rembg_fn = remove

    total = len(frames)
    for i, path in enumerate(frames, 1):
        img = Image.open(path).convert("RGBA")

        # resize keeping aspect ratio
        ratio = height / img.height
        new_w = round(img.width * ratio)
        img = img.resize((new_w, height), Image.LANCZOS)

        if rembg_fn is not None:
            img = rembg_fn(img)
            img = clamp_alpha(img)

        img.save(path)
        print(f"\r  Processing: {i}/{total} ({i * 100 // total}%)", end="", flush=True)
    print()


def make_icon(src_frame: Path, out_path: Path, size: int = 64):
    from PIL import Image

    img = Image.open(src_frame).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    img.save(out_path)


def copy_configs():
    """Copy game config JSONs to assets/config/ for runtime loading."""
    config_src = ROOT / "Assets" / "Config"
    config_dst = ASSETS / "config"
    config_dst.mkdir(parents=True, exist_ok=True)

    for name in ("game_difficulty.json", "video_segments.json"):
        src = config_src / name
        if src.exists():
            shutil.copy2(src, config_dst / name)
            print(f"  Copied {name}")
        else:
            print(f"  Skipped {name} (not found at {src})")


# ── main ───────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Prepare Nailong desktop pet assets")
    ap.add_argument(
        "--video", type=Path,
        default=ROOT / "Assets" / "Video" / "how_to_train_your_nailong_h264.mp4",
    )
    ap.add_argument(
        "--height", type=int, default=256,
        help="Pet sprite height in pixels (default: 256)",
    )
    ap.add_argument("--idle-fps", type=int, default=10)
    ap.add_argument("--laugh-fps", type=int, default=12)
    ap.add_argument(
        "--laugh-end", type=float, default=None,
        help="End time in seconds for laugh segment (default: auto-detect video duration)",
    )
    ap.add_argument(
        "--no-rembg", action="store_true",
        help="Skip background removal (for quick testing)",
    )
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"Video not found: {args.video}")

    ffmpeg = find_ffmpeg()
    print(f"Video : {args.video.name}")
    print(f"ffmpeg: {ffmpeg}")
    print(f"Height: {args.height}px  |  rembg: {'OFF' if args.no_rembg else 'ON'}")

    # Auto-detect video duration for laugh segment end
    laugh_end = args.laugh_end
    if laugh_end is None:
        duration = get_video_duration(ffmpeg, args.video)
        if duration:
            laugh_end = duration
            print(f"Video duration: {duration:.2f}s (auto-detected)")
        else:
            laugh_end = 15.4  # fallback from video_segments.json
            print(f"Video duration: {laugh_end}s (fallback)")

    ASSETS.mkdir(parents=True, exist_ok=True)

    # ── idle (stare segment: 0 – 1 s) ─────────────────────────
    idle_dir = ASSETS / "idle"
    print("\n[1/5] Idle frames (0-1 s) ...")
    idle_frames = extract_frames(ffmpeg, args.video, idle_dir, 0, 1.0, args.idle_fps)
    print(f"  Extracted {len(idle_frames)} frames")
    process_frames(idle_frames, args.height, not args.no_rembg)

    # ── laugh (1 s – end) ──────────────────────────────────────
    laugh_dir = ASSETS / "laugh"
    print(f"[2/5] Laugh frames (1-{laugh_end:.1f} s) ...")
    laugh_frames = extract_frames(
        ffmpeg, args.video, laugh_dir, 1.0, laugh_end, args.laugh_fps,
    )
    print(f"  Extracted {len(laugh_frames)} frames")
    process_frames(laugh_frames, args.height, not args.no_rembg)

    # ── audio extraction ───────────────────────────────────────
    print("[3/5] Extracting audio ...")
    stare_wav = ASSETS / "stare.wav"
    if extract_audio(ffmpeg, args.video, stare_wav, 0, 1.0):
        print(f"  Saved {stare_wav.name} (0-1s)")
    else:
        print(f"  Failed to extract stare audio")

    laugh_wav = ASSETS / "laugh.wav"
    if extract_audio(ffmpeg, args.video, laugh_wav, 1.0):
        print(f"  Saved {laugh_wav.name} (1s-end)")
    else:
        print(f"  Failed to extract laugh audio")

    # ── tray icon ──────────────────────────────────────────────
    print("[4/5] Creating tray icon (from last idle frame) ...")
    icon_path = ASSETS / "icon.png"
    last_idle = sorted(idle_dir.glob("*.png"))[-1]
    make_icon(last_idle, icon_path)
    print(f"  Saved {icon_path}")

    # ── config files ───────────────────────────────────────────
    print("[5/5] Copying config files ...")
    copy_configs()

    # summary
    n_idle = len(list(idle_dir.glob("*.png")))
    n_laugh = len(list(laugh_dir.glob("*.png")))
    has_stare = stare_wav.exists()
    has_laugh = laugh_wav.exists()
    print(f"\nDone!")
    print(f"  idle:  {n_idle} frames")
    print(f"  laugh: {n_laugh} frames")
    print(f"  audio: stare={'OK' if has_stare else 'MISSING'}  laugh={'OK' if has_laugh else 'MISSING'}")
    print(f"  icon:  64x64")
    print(f"Assets in: {ASSETS}")
    print("Next:  python main.py")


if __name__ == "__main__":
    main()
