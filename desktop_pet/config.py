"""Configuration loading for game difficulty and video segments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DifficultyParams:
    nailong_laugh_min_ms: int = 5000
    nailong_laugh_max_ms: int = 12000
    calibration_ms: int = 2500
    smile_threshold: float = 0.28
    consecutive_frames_to_confirm: int = 4
    lost_face_grace_ms: int = 1500
    lost_face_invalid_ms: int = 5000


@dataclass
class VideoSegments:
    stare_start_ms: int = 0
    stare_end_ms: int = 1000
    laugh_trigger_frame_ms: int = 1000
    laugh_segment_end_ms: int | None = None
    duration_ms: int = 15400
    fps: float = 30.0
    pause_after_stare_min: int = 800
    pause_after_stare_max: int = 1200
    pause_before_stare_min: int = 400
    pause_before_stare_max: int = 800


# Hardcoded fallback presets (mirror Assets/Config/game_difficulty.json)
_DEFAULT_DIFFICULTIES: dict[str, DifficultyParams] = {
    "easy": DifficultyParams(
        nailong_laugh_min_ms=8000,
        nailong_laugh_max_ms=18000,
        calibration_ms=3000,
        smile_threshold=0.30,
        consecutive_frames_to_confirm=4,
        lost_face_grace_ms=2000,
        lost_face_invalid_ms=7000,
    ),
    "normal": DifficultyParams(
        nailong_laugh_min_ms=5000,
        nailong_laugh_max_ms=12000,
        calibration_ms=2500,
        smile_threshold=0.28,
        consecutive_frames_to_confirm=4,
        lost_face_grace_ms=1500,
        lost_face_invalid_ms=5000,
    ),
    "hard": DifficultyParams(
        nailong_laugh_min_ms=3000,
        nailong_laugh_max_ms=8000,
        calibration_ms=2000,
        smile_threshold=0.25,
        consecutive_frames_to_confirm=3,
        lost_face_grace_ms=1000,
        lost_face_invalid_ms=4000,
    ),
}


def load_difficulties(path: Path | None = None) -> dict[str, DifficultyParams]:
    """Load difficulty presets from JSON, falling back to hardcoded defaults."""
    if path is None or not path.exists():
        return dict(_DEFAULT_DIFFICULTIES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        modes = data.get("modes", {})
        result: dict[str, DifficultyParams] = {}
        for name, vals in modes.items():
            result[name] = DifficultyParams(
                nailong_laugh_min_ms=vals.get("nailong_laugh_min_ms", 5000),
                nailong_laugh_max_ms=vals.get("nailong_laugh_max_ms", 12000),
                calibration_ms=vals.get("calibration_ms", 2500),
                smile_threshold=vals.get("smile_threshold", 0.28),
                consecutive_frames_to_confirm=vals.get("consecutive_frames_to_confirm", 4),
                lost_face_grace_ms=vals.get("lost_face_grace_ms", 1500),
                lost_face_invalid_ms=vals.get("lost_face_invalid_ms", 5000),
            )
        return result if result else dict(_DEFAULT_DIFFICULTIES)
    except Exception:
        return dict(_DEFAULT_DIFFICULTIES)


def load_segments(path: Path | None = None) -> VideoSegments:
    """Load video segment config from JSON, falling back to hardcoded defaults."""
    if path is None or not path.exists():
        return VideoSegments()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pause_after = data.get("pause_after_stare_ms_range", [800, 1200])
        pause_before = data.get("pause_before_stare_ms_range", [400, 800])
        return VideoSegments(
            stare_start_ms=data.get("stare_start_ms", 0),
            stare_end_ms=data.get("stare_end_ms", 1000),
            laugh_trigger_frame_ms=data.get("laugh_trigger_frame_ms", 1000),
            laugh_segment_end_ms=data.get("laugh_segment_end_ms"),
            duration_ms=data.get("duration_ms", 15400),
            fps=data.get("fps", 30.0),
            pause_after_stare_min=pause_after[0] if len(pause_after) >= 2 else 800,
            pause_after_stare_max=pause_after[1] if len(pause_after) >= 2 else 1200,
            pause_before_stare_min=pause_before[0] if len(pause_before) >= 2 else 400,
            pause_before_stare_max=pause_before[1] if len(pause_before) >= 2 else 800,
        )
    except Exception:
        return VideoSegments()
