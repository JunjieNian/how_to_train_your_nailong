"""
video_controller.py — 4-phase stare cycle with sprite animation and audio.

Faithful port of Media/VideoController.h/cpp.

Phase sequence (one cycle):
  Forward     animate idle frames 0→N, play stare audio
  HoldEnd     pause on last frame, fire on_cycle_boundary, random 800-1200ms
  Reverse     animate idle frames N→0, stop audio
  HoldStart   pause on first frame, random 400-800ms, then back to Forward

Laugh: deferred to HoldEnd boundary for seamless visual cut (exact C++ logic).
Ambient: simple pingpong loop with no audio or callbacks.
"""

from __future__ import annotations

import enum
import random
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from config import VideoSegments

# Optional: audio via QMediaPlayer (may not be available on all platforms)
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    _HAS_AUDIO = True
except ImportError:
    _HAS_AUDIO = False


class CyclePhase(enum.IntEnum):
    Idle = 0
    Forward = 1
    HoldEnd = 2
    Reverse = 3
    HoldStart = 4
    Laughing = 5


class VideoController:
    """Drives sprite animation through the 4-phase stare cycle with audio."""

    def __init__(
        self,
        label: QLabel,
        segments: VideoSegments,
        idle_dir: Path,
        laugh_dir: Path,
        stare_audio_path: Path | None = None,
        laugh_audio_path: Path | None = None,
    ):
        self._label = label
        self._segments = segments
        self._phase = CyclePhase.Idle
        self._laugh_pending = False
        self._ambient = False

        # Load frames
        self._idle_frames = self._load_frames(idle_dir)
        self._laugh_frames = self._load_frames(laugh_dir)
        self._frame_idx = 0

        # Reverse idle frames (for reverse phase)
        self._idle_reversed = list(reversed(self._idle_frames))

        # Audio players
        self._stare_player: QMediaPlayer | None = None
        self._stare_output: QAudioOutput | None = None
        self._laugh_player: QMediaPlayer | None = None
        self._laugh_output: QAudioOutput | None = None

        if _HAS_AUDIO and stare_audio_path and stare_audio_path.exists():
            self._stare_player = QMediaPlayer()
            self._stare_output = QAudioOutput()
            self._stare_player.setAudioOutput(self._stare_output)
            self._stare_player.setSource(QUrl.fromLocalFile(str(stare_audio_path)))

        if _HAS_AUDIO and laugh_audio_path and laugh_audio_path.exists():
            self._laugh_player = QMediaPlayer()
            self._laugh_output = QAudioOutput()
            self._laugh_player.setAudioOutput(self._laugh_output)
            self._laugh_player.setSource(QUrl.fromLocalFile(str(laugh_audio_path)))

        # Animation timer (drives frame advancement)
        self._anim_timer = QTimer()
        self._anim_timer.timeout.connect(self._on_anim_tick)

        # Hold timer (single-shot for pause phases)
        self._hold_timer = QTimer()
        self._hold_timer.setSingleShot(True)

        # Callback: fired at every Forward→HoldEnd boundary
        self.on_cycle_boundary: Callable[[], None] | None = None

        # Current frame set being animated
        self._current_frames: list[QPixmap] = []

    @staticmethod
    def _load_frames(frame_dir: Path) -> list[QPixmap]:
        if not frame_dir.is_dir():
            return []
        paths = sorted(frame_dir.glob("*.png"))
        return [QPixmap(str(p)) for p in paths]

    @property
    def phase(self) -> CyclePhase:
        return self._phase

    # ── stare cycle (game mode) ────────────────────────────────

    def begin_stare_cycle(self) -> None:
        """Start the 4-phase cycle from Forward. Called by GameEngine."""
        self.stop()
        self._laugh_pending = False
        self._enter_forward()

    def trigger_laugh(self) -> None:
        """Defer laugh to next HoldEnd boundary for seamless cut (exact C++ logic)."""
        self._laugh_pending = True

    def stop(self) -> None:
        """Stop all animation and audio. Reset to first idle frame."""
        self._anim_timer.stop()
        self._hold_timer.stop()
        self._stop_all_audio()
        self._phase = CyclePhase.Idle
        self._ambient = False
        if self._idle_frames:
            self._label.setPixmap(self._idle_frames[0])

    # ── ambient mode (simple pingpong, no audio, no callbacks) ─

    def start_ambient(self) -> None:
        """Start a gentle pingpong idle loop (no game logic)."""
        self.stop()
        if not self._idle_frames:
            return
        # Build pingpong sequence: 0,1,...,N,N-1,...,1
        if len(self._idle_frames) > 2:
            self._current_frames = (
                self._idle_frames + self._idle_frames[-2:0:-1]
            )
        else:
            self._current_frames = list(self._idle_frames)
        self._frame_idx = 0
        self._ambient = True
        self._anim_timer.start(100)  # 10 fps

    # ── phase transitions (port of VideoController::Impl) ──────

    def _enter_forward(self) -> None:
        """Phase 1: animate idle frames 0→N, play stare audio."""
        self._phase = CyclePhase.Forward
        self._current_frames = self._idle_frames
        self._frame_idx = 0
        self._ambient = False
        self._play_stare_audio()
        self._anim_timer.start(100)  # 10 fps

    def _enter_hold_end(self) -> None:
        """Phase 2: pause on last frame, fire boundary, check laugh."""
        self._phase = CyclePhase.HoldEnd
        self._anim_timer.stop()

        # Fire cycle boundary (GameEngine checks deadline here)
        if self.on_cycle_boundary:
            self.on_cycle_boundary()

        # If laugh was requested, enter laugh immediately (exact C++ logic)
        if self._laugh_pending:
            self._laugh_pending = False
            self._enter_laugh()
            return

        self._stop_stare_audio()

        # Schedule hold, then reverse
        hold_ms = random.randint(
            self._segments.pause_after_stare_min,
            self._segments.pause_after_stare_max,
        )
        self._schedule_hold(hold_ms, self._enter_reverse)

    def _enter_reverse(self) -> None:
        """Phase 3: animate idle frames N→0."""
        self._phase = CyclePhase.Reverse
        self._current_frames = self._idle_reversed
        self._frame_idx = 0
        self._ambient = False
        self._anim_timer.start(100)  # 10 fps

    def _enter_hold_start(self) -> None:
        """Phase 4: pause on first frame, then back to Forward."""
        self._phase = CyclePhase.HoldStart
        self._anim_timer.stop()

        hold_ms = random.randint(
            self._segments.pause_before_stare_min,
            self._segments.pause_before_stare_max,
        )
        self._schedule_hold(hold_ms, self._enter_forward)

    def _enter_laugh(self) -> None:
        """Play laugh frames sequentially, play laugh audio."""
        self._phase = CyclePhase.Laughing
        self._current_frames = self._laugh_frames
        self._frame_idx = 0
        self._ambient = False
        self._stop_stare_audio()
        self._play_laugh_audio()
        self._anim_timer.start(83)  # ~12 fps

    def _schedule_hold(self, ms: int, callback) -> None:
        """Single-shot hold timer (replaces C++ ScheduleHold)."""
        self._hold_timer.stop()
        try:
            self._hold_timer.timeout.disconnect()
        except TypeError:
            pass
        self._hold_timer.setInterval(ms)
        self._hold_timer.timeout.connect(callback)
        self._hold_timer.start()

    # ── animation tick ─────────────────────────────────────────

    def _on_anim_tick(self) -> None:
        if not self._current_frames:
            return

        # Ambient mode: loop forever
        if self._ambient:
            idx = self._frame_idx % len(self._current_frames)
            self._label.setPixmap(self._current_frames[idx])
            self._frame_idx += 1
            return

        # Game mode: advance through current frame set
        if self._frame_idx < len(self._current_frames):
            self._label.setPixmap(self._current_frames[self._frame_idx])
            self._frame_idx += 1
        else:
            # Reached end of current frame set — transition
            if self._phase == CyclePhase.Forward:
                self._enter_hold_end()
            elif self._phase == CyclePhase.Reverse:
                self._enter_hold_start()
            elif self._phase == CyclePhase.Laughing:
                # Stay on last frame (game handles what happens next)
                self._anim_timer.stop()

    # ── audio helpers ──────────────────────────────────────────

    def _play_stare_audio(self) -> None:
        if self._stare_player:
            self._stare_player.setPosition(0)
            self._stare_player.play()

    def _stop_stare_audio(self) -> None:
        if self._stare_player:
            self._stare_player.stop()

    def _play_laugh_audio(self) -> None:
        if self._laugh_player:
            self._laugh_player.setPosition(0)
            self._laugh_player.play()

    def _stop_all_audio(self) -> None:
        self._stop_stare_audio()
        if self._laugh_player:
            self._laugh_player.stop()
