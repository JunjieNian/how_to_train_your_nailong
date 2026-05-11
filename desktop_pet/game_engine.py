"""
game_engine.py — 9-state FSM for the don't-laugh challenge.

Faithful port of Core/GameEngine.h/cpp + Core/GameState.h.
All methods must be called from the GUI thread.
"""

from __future__ import annotations

import enum
import random
import time
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, QTimer

from config import DifficultyParams


# ── enums (mirror GameState.h) ─────────────────────────────────────


class GameState(enum.IntEnum):
    Idle = 0
    CameraWarmup = 1
    Calibration = 2
    Countdown = 3
    StareLoop = 4
    UserLaughDetected = 5
    NailongLaughTriggered = 6
    Result = 7
    Invalid = 8


class Winner(enum.IntEnum):
    NoOne = 0
    User = 1       # nailong laughed first → user wins
    Nailong = 2    # user laughed first → nailong wins


class Difficulty(enum.IntEnum):
    Easy = 0
    Normal = 1
    Hard = 2


# ── data ───────────────────────────────────────────────────────────


@dataclass
class SmileSample:
    t: float              # monotonic time (seconds)
    face_found: bool
    smile_score: float    # baseline-subtracted, 0..1
    is_smiling: bool      # sliding-window confirmed
    calibrated: bool


# ── view protocol ──────────────────────────────────────────────────


class IGameView(Protocol):
    def show_overlay(self, text: str) -> None: ...
    def clear_overlay(self) -> None: ...
    def start_countdown(self, seconds: int) -> None: ...
    def begin_stare_cycle(self) -> None: ...
    def trigger_nailong_laugh(self) -> None: ...
    def show_result(self, winner: Winner) -> None: ...
    def request_calibration(self, start: bool) -> None: ...


# ── engine ─────────────────────────────────────────────────────────


class GameEngine(QObject):
    """Central game state machine — port of Core/GameEngine."""

    def __init__(self, view: IGameView, parent: QObject | None = None):
        super().__init__(parent)
        self._view = view
        self._state = GameState.Idle
        self._difficulty = Difficulty.Normal
        self._params = DifficultyParams()
        self._last_winner = Winner.NoOne

        self._nailong_laugh_deadline: float = 0.0
        self._lost_face_since: float | None = None
        self._countdown_remaining: int = 0

        # Timers (mirror the 3 DispatcherQueueTimers in C++)
        self._delay_timer = QTimer(self)
        self._delay_timer.setSingleShot(True)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)

    # ── properties ─────────────────────────────────────────────

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def last_winner(self) -> Winner:
        return self._last_winner

    # ── UI inputs ──────────────────────────────────────────────

    def set_difficulty(self, d: Difficulty, params: DifficultyParams) -> None:
        self._difficulty = d
        self._params = params

    def start_challenge(self) -> None:
        """Idle/Result/Invalid → CameraWarmup."""
        if self._state not in (GameState.Idle, GameState.Result, GameState.Invalid):
            return
        self._state = GameState.CameraWarmup
        self._view.show_overlay("准备摄像头…")

    def reset(self) -> None:
        """Any state → Idle."""
        self._stop_all_timers()
        self._view.clear_overlay()
        self._view.request_calibration(False)
        self._last_winner = Winner.NoOne
        self._lost_face_since = None
        self._state = GameState.Idle

    # ── detector inputs ────────────────────────────────────────

    def on_detector_ready(self) -> None:
        """Called when first valid face is detected."""
        if self._state != GameState.CameraWarmup:
            return
        self._enter_calibration()

    def on_detector_lost(self, reason: str = "") -> None:
        """Called when camera/model fails."""
        self._stop_all_timers()
        self._view.show_overlay("摄像头检测进程已断开")
        self._state = GameState.Invalid

    def on_smile_sample(self, s: SmileSample) -> None:
        """Process a smile detection sample."""
        # Track lost-face in any "live" state
        live = self._state in (GameState.Countdown, GameState.StareLoop)

        if live:
            if not s.face_found:
                if self._lost_face_since is None:
                    self._lost_face_since = s.t
                missing_ms = (s.t - self._lost_face_since) * 1000
                if missing_ms > self._params.lost_face_grace_ms:
                    self._view.show_overlay("奶龙看不见你了…")
                if missing_ms > self._params.lost_face_invalid_ms:
                    self._declare_invalid()
                    return
            else:
                if self._lost_face_since is not None:
                    self._view.clear_overlay()
                    self._lost_face_since = None

        # Smile triggers user-loss only during StareLoop
        if (self._state == GameState.StareLoop
                and s.is_smiling and s.calibrated):
            self._declare_winner(Winner.Nailong)  # user laughed → nailong wins

    # ── video controller input ─────────────────────────────────

    def on_stare_cycle_boundary(self) -> None:
        """Called at end of each forward-stare phase."""
        if self._state != GameState.StareLoop:
            return
        if time.monotonic() >= self._nailong_laugh_deadline:
            self._declare_winner(Winner.User)  # nailong laughed first → user wins

    # ── internal transitions ───────────────────────────────────

    def _stop_all_timers(self) -> None:
        self._delay_timer.stop()
        self._countdown_timer.stop()

    def _delay_once(self, ms: int, fn) -> None:
        """Fire fn after ms milliseconds (single-shot)."""
        self._delay_timer.stop()
        try:
            self._delay_timer.timeout.disconnect()
        except TypeError:
            pass
        self._delay_timer.setInterval(ms)
        self._delay_timer.timeout.connect(fn)
        self._delay_timer.start()

    def _enter_calibration(self) -> None:
        self._state = GameState.Calibration
        self._view.show_overlay("看着奶龙，先别笑（校准中…）")
        self._view.request_calibration(True)

        def on_done():
            if self._state != GameState.Calibration:
                return
            self._view.request_calibration(False)
            self._enter_countdown()

        self._delay_once(self._params.calibration_ms, on_done)

    def _enter_countdown(self) -> None:
        self._state = GameState.Countdown
        self._countdown_remaining = 3
        self._view.start_countdown(self._countdown_remaining)
        self._view.show_overlay("3")

        self._countdown_timer.stop()
        try:
            self._countdown_timer.timeout.disconnect()
        except TypeError:
            pass

        def on_tick():
            if self._state != GameState.Countdown:
                self._countdown_timer.stop()
                return
            self._countdown_remaining -= 1
            if self._countdown_remaining > 0:
                self._view.start_countdown(self._countdown_remaining)
                self._view.show_overlay(str(self._countdown_remaining))
            else:
                self._countdown_timer.stop()
                self._view.clear_overlay()
                self._enter_stare_loop()

        self._countdown_timer.timeout.connect(on_tick)
        self._countdown_timer.start()

    def _enter_stare_loop(self) -> None:
        self._state = GameState.StareLoop
        delay_ms = random.randint(
            self._params.nailong_laugh_min_ms,
            self._params.nailong_laugh_max_ms,
        )
        self._nailong_laugh_deadline = time.monotonic() + delay_ms / 1000.0
        self._lost_face_since = None
        self._view.begin_stare_cycle()

    def _declare_winner(self, w: Winner) -> None:
        self._last_winner = w

        if w == Winner.User:
            # Nailong laughed first — trigger laugh, then show result after 300ms
            self._state = GameState.NailongLaughTriggered
            self._view.trigger_nailong_laugh()

            def show():
                self._state = GameState.Result
                self._view.show_result(w)

            self._delay_once(300, show)
        else:
            # User laughed first — show overlay, then trigger nailong laugh after 500ms
            self._state = GameState.UserLaughDetected
            self._view.show_overlay("你笑了！奶龙赢")

            def laugh_and_show():
                self._view.trigger_nailong_laugh()
                self._state = GameState.Result
                self._view.show_result(w)

            self._delay_once(500, laugh_and_show)

    def _declare_invalid(self) -> None:
        self._state = GameState.Invalid
        self._view.show_overlay("奶龙看不见你了 — 本局作废")
        self._delay_once(1500, self.reset)
