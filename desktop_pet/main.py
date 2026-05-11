#!/usr/bin/env python3
"""
Nailong Desktop Pet — Full Game Logic

A transparent, always-on-top animated Nailong desktop pet with the
don't-laugh challenge game. Faithful port of the WinUI 3 C++ game.

Features:
  - 9-state FSM game engine with configurable difficulty
  - 4-phase stare cycle with audio sync
  - Embedded MediaPipe smile detection via camera
  - Frameless transparent window, drag to move, system tray
  - Auto-start game on launch (default when packaged as .exe)
  - Auto-restart rounds after each result

Usage:
    python main.py                # auto-start game with camera
    python main.py --no-camera    # ambient mode only (no smile detection)
    python main.py --no-auto      # manual start via right-click menu

Prerequisites:
    1. Run prepare_assets.py to generate sprite frames + audio
    2. pip install -r requirements.txt
    3. Download face_landmarker.task into this directory
"""

import os
import sys

# ── Anaconda Qt DLL conflict fix ───────────────────────────────────
# Anaconda's `conda activate` registers its own Qt DLLs via the Windows
# AddDllDirectory API.  These are ABI-incompatible with pip-installed
# PySide6 and cause "DLL load failed: 找不到指定的程序".  Cleaning PATH
# alone is NOT enough (Python 3.8+ ignores PATH for DLL search).
#
# Fix: pre-load PySide6's own Qt6Core.dll etc. by absolute path before
# any `import PySide6` triggers the default (broken) DLL search.
if sys.platform == "win32":
    import ctypes
    import importlib.util

    _spec = importlib.util.find_spec("PySide6")
    if _spec and _spec.submodule_search_locations:
        _psd = _spec.submodule_search_locations[0]

        # Locate the directory that contains Qt6Core.dll
        _qt_dir = None
        for _sub in ("", "Qt6\\bin", "Qt\\bin"):
            _candidate = os.path.join(_psd, _sub) if _sub else _psd
            if os.path.isfile(os.path.join(_candidate, "Qt6Core.dll")):
                _qt_dir = _candidate
                break

        if _qt_dir:
            # 1) add_dll_directory so transitive deps resolve here too
            try:
                os.add_dll_directory(_qt_dir)
            except OSError:
                pass

            # 2) pre-load core Qt DLLs by absolute path — once loaded,
            #    Windows will reuse them instead of finding Anaconda's
            for _dll in (
                "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
                "Qt6Network.dll", "Qt6Multimedia.dll",
                "Qt6DBus.dll", "Qt6OpenGL.dll",
            ):
                _path = os.path.join(_qt_dir, _dll)
                if os.path.isfile(_path):
                    try:
                        ctypes.cdll.LoadLibrary(_path)
                    except OSError:
                        pass

    # also strip Anaconda from PATH as a belt-and-suspenders measure
    _clean = [p for p in os.environ.get("PATH", "").split(";")
              if "library\\bin" not in p.lower()]
    os.environ["PATH"] = ";".join(_clean)

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap, QIcon, QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QMenu,
    QSystemTrayIcon,
)

from config import load_difficulties, load_segments, DifficultyParams
from game_engine import (
    GameEngine, GameState, Winner, Difficulty,
    SmileSample as EngineSmileSample,
)
from video_controller import VideoController
from smile_detector import SmileDetector, SmileSample as DetectorSmileSample

# ── path resolution (script vs frozen .exe) ───────────────────────
_FROZEN = getattr(sys, "frozen", False)
if _FROZEN:
    # PyInstaller 6.x --onedir puts data in _internal/ (sys._MEIPASS)
    _BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    _BASE = Path(__file__).parent

ASSETS = _BASE / "assets"
CONFIG = ASSETS / "config"


class DesktopPet(QWidget):
    """Frameless transparent widget implementing IGameView.

    Orchestrates GameEngine + VideoController + SmileDetector.
    """

    def __init__(self, no_camera: bool = False, auto_start: bool = True):
        super().__init__()
        self._no_camera = no_camera
        self._auto_start = auto_start and not no_camera

        # ── window setup ───────────────────────────────────────
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── config ─────────────────────────────────────────────
        self._difficulties = load_difficulties(CONFIG / "game_difficulty.json")
        self._segments = load_segments(CONFIG / "video_segments.json")
        self._difficulty = Difficulty.Normal
        self._difficulty_name = "normal"

        # ── sprite label ───────────────────────────────────────
        self._sprite_label = QLabel(self)
        self._sprite_label.setStyleSheet("background:transparent")

        # Determine sprite size from first idle frame
        idle_dir = ASSETS / "idle"
        test_frames = sorted(idle_dir.glob("*.png")) if idle_dir.is_dir() else []
        if test_frames:
            pm = QPixmap(str(test_frames[0]))
            sprite_size = pm.size()
        else:
            sprite_size = QSize(180, 256)

        # Widget size: sprite + room for overlay floating above
        self._overlay_height = 30
        self.setFixedSize(
            max(sprite_size.width(), 120),
            sprite_size.height() + self._overlay_height,
        )
        self._sprite_label.setFixedSize(sprite_size)
        # Center sprite horizontally, pin to bottom
        sprite_x = (self.width() - sprite_size.width()) // 2
        self._sprite_label.move(sprite_x, self._overlay_height)

        # ── overlay label (small text floating above sprite) ───
        self._overlay_label = QLabel(self)
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_label.setWordWrap(True)
        self._overlay_label.setStyleSheet(
            "background: rgba(0, 0, 0, 160);"
            "color: white;"
            "font-weight: bold;"
            "font-size: 9pt;"
            "border-radius: 4px;"
            "padding: 2px 6px;"
        )
        self._overlay_label.setFixedWidth(self.width())
        self._overlay_label.move(0, 0)
        self._overlay_label.hide()

        # ── video controller ───────────────────────────────────
        stare_audio = ASSETS / "stare.wav"
        laugh_audio = ASSETS / "laugh.wav"
        self._video = VideoController(
            label=self._sprite_label,
            segments=self._segments,
            idle_dir=ASSETS / "idle",
            laugh_dir=ASSETS / "laugh",
            stare_audio_path=stare_audio if stare_audio.exists() else None,
            laugh_audio_path=laugh_audio if laugh_audio.exists() else None,
        )

        # ── game engine ───────────────────────────────────────
        self._engine = GameEngine(view=self, parent=self)
        params = self._difficulties.get(self._difficulty_name, DifficultyParams())
        self._engine.set_difficulty(self._difficulty, params)

        # Wire video boundary → engine
        self._video.on_cycle_boundary = self._engine.on_stare_cycle_boundary

        # ── smile detector (created on demand) ─────────────────
        self._detector: SmileDetector | None = None

        # ── initial position: bottom-right, above taskbar ──────
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.right() - self.width() - 30,
                geo.bottom() - self.height() - 10,
            )

        # ── drag state ─────────────────────────────────────────
        self._drag_origin = None

        # ── tracked menu actions (for enable/disable) ──────────
        self._start_action: QAction | None = None
        self._reset_action: QAction | None = None

        # ── system tray ────────────────────────────────────────
        self._tray_menu = self._build_menu()
        self._init_tray()

        # ── start ambient mode ─────────────────────────────────
        self._video.start_ambient()

        # ── auto-start game after brief ambient warmup ─────────
        if self._auto_start:
            QTimer.singleShot(2000, self._start_challenge)

    # ── IGameView implementation ───────────────────────────────

    def show_overlay(self, text: str) -> None:
        self._overlay_label.setText(text)
        self._overlay_label.adjustSize()
        # Fit width to content, clamp to widget width
        hint_w = self._overlay_label.sizeHint().width() + 12
        label_w = min(max(hint_w, 60), self.width())
        self._overlay_label.setFixedWidth(label_w)
        # Center above sprite
        x = (self.width() - label_w) // 2
        self._overlay_label.move(max(0, x), 0)
        self._overlay_label.show()

    def clear_overlay(self) -> None:
        self._overlay_label.hide()

    def start_countdown(self, seconds: int) -> None:
        pass  # overlay text is set by engine via show_overlay

    def begin_stare_cycle(self) -> None:
        self._video.begin_stare_cycle()

    def trigger_nailong_laugh(self) -> None:
        self._video.trigger_laugh()

    def show_result(self, winner: Winner) -> None:
        if winner == Winner.User:
            self.show_overlay("奶龙先笑了！你赢了")
        elif winner == Winner.Nailong:
            self.show_overlay("你笑了！奶龙赢")
        self._set_controls_enabled(True)

        # Auto-restart next round after showing result
        if self._auto_start:
            QTimer.singleShot(5000, self._auto_restart)

    def request_calibration(self, start: bool) -> None:
        if self._detector:
            if start:
                self._detector.start_calibration()
            else:
                self._detector.end_calibration()

    # ── game lifecycle ─────────────────────────────────────────

    def _auto_restart(self) -> None:
        """Reset and start a new round (called by auto-start timer)."""
        if not self._auto_start:
            return
        # Only restart if we're in a finished state
        if self._engine.state not in (
            GameState.Idle, GameState.Result, GameState.Invalid,
        ):
            return
        self._reset()
        QTimer.singleShot(2000, self._start_challenge)

    def _start_challenge(self) -> None:
        if self._engine.state not in (
            GameState.Idle, GameState.Result, GameState.Invalid,
        ):
            return

        self._set_controls_enabled(False)
        self._video.stop()
        self._engine.start_challenge()

        if self._no_camera:
            self.show_overlay("未启用摄像头\n仅观赏模式")
            QTimer.singleShot(2000, self._abort_no_camera)
            return

        # Start detector thread
        self._cleanup_detector()
        self._detector = SmileDetector(
            camera_index=0,
            model_path=self._find_model(),
            fps=15.0,
            parent=self,
        )
        self._detector.detector_ready.connect(self._on_detector_ready)
        self._detector.detector_lost.connect(self._on_detector_lost)
        self._detector.sample_ready.connect(self._on_sample)
        self._detector.start()

    def _abort_no_camera(self) -> None:
        self.clear_overlay()
        self._engine.reset()
        self._video.start_ambient()
        self._set_controls_enabled(True)

    def _reset(self) -> None:
        self._cleanup_detector()
        self._video.stop()
        self._engine.reset()
        self._video.start_ambient()
        self._set_controls_enabled(True)

    def _cleanup_detector(self) -> None:
        if self._detector is not None:
            self._detector.request_stop()
            self._detector.wait(2000)
            self._detector = None

    def _on_detector_ready(self) -> None:
        self._engine.on_detector_ready()

    def _on_detector_lost(self, reason: str) -> None:
        self._engine.on_detector_lost(reason)
        self._set_controls_enabled(True)

    def _on_sample(self, s: DetectorSmileSample) -> None:
        engine_sample = EngineSmileSample(
            t=s.t,
            face_found=s.face_found,
            smile_score=s.smile_score,
            is_smiling=s.is_smiling,
            calibrated=s.calibrated,
        )
        self._engine.on_smile_sample(engine_sample)

    @staticmethod
    def _find_model() -> str | None:
        """Search for face_landmarker.task in common locations."""
        candidates = [
            _BASE / "face_landmarker.task",
            _BASE / "models" / "face_landmarker.task",
        ]
        if not _FROZEN:
            candidates.append(
                Path(__file__).parent.parent / "tools" / "smile_sidecar" / "face_landmarker.task",
            )
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    # ── menu ───────────────────────────────────────────────────

    def _set_controls_enabled(self, enabled: bool) -> None:
        if self._start_action:
            self._start_action.setEnabled(enabled)

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        # Difficulty submenu
        diff_menu = menu.addMenu("难度")
        diff_group = QActionGroup(self)
        diff_group.setExclusive(True)

        for label, key, diff_enum in [
            ("简单", "easy", Difficulty.Easy),
            ("普通（默认）", "normal", Difficulty.Normal),
            ("困难", "hard", Difficulty.Hard),
        ]:
            act = QAction(label, self, checkable=True)
            act.setChecked(key == self._difficulty_name)
            act.triggered.connect(
                lambda checked, k=key, d=diff_enum: self._set_difficulty(k, d),
            )
            diff_group.addAction(act)
            diff_menu.addAction(act)

        menu.addSeparator()

        self._start_action = QAction("开始挑战", self)
        self._start_action.triggered.connect(self._start_challenge)
        menu.addAction(self._start_action)

        # Auto-play toggle
        pause_label = "暂停游戏" if self._auto_start else "继续游戏"
        act_toggle = QAction(pause_label, self)
        act_toggle.triggered.connect(self._toggle_auto)
        menu.addAction(act_toggle)

        self._reset_action = QAction("重置", self)
        self._reset_action.triggered.connect(self._reset)
        menu.addAction(self._reset_action)

        menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        return menu

    def _toggle_auto(self) -> None:
        self._auto_start = not self._auto_start
        if self._auto_start:
            # Resume: if idle, start a new round
            if self._engine.state in (GameState.Idle, GameState.Result, GameState.Invalid):
                QTimer.singleShot(1000, self._start_challenge)
        else:
            # Pause: if in result, don't auto-restart (reset to ambient)
            if self._engine.state in (GameState.Result, GameState.Invalid):
                self._reset()
        # Rebuild tray menu to reflect new label
        self._tray_menu = self._build_menu()
        self._tray.setContextMenu(self._tray_menu)

    def _set_difficulty(self, name: str, d: Difficulty) -> None:
        self._difficulty_name = name
        self._difficulty = d
        params = self._difficulties.get(name, DifficultyParams())
        self._engine.set_difficulty(d, params)

    def _init_tray(self) -> None:
        icon_file = ASSETS / "icon.png"
        icon = QIcon(str(icon_file)) if icon_file.exists() else QIcon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_click)
        self._tray.show()

    def _on_tray_click(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()

    def _quit(self) -> None:
        self._cleanup_detector()
        QApplication.quit()

    # ── mouse interaction ──────────────────────────────────────

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_origin is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_origin = None

    def contextMenuEvent(self, ev) -> None:
        menu = self._build_menu()
        menu.exec(ev.globalPosition().toPoint())


# ── entry point ───────────────────────────────────────────────────


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Nailong Desktop Pet")
    ap.add_argument(
        "--no-camera", action="store_true",
        help="Disable camera / smile detection (ambient mode only)",
    )
    ap.add_argument(
        "--no-auto", action="store_true",
        help="Don't auto-start the game (use right-click menu to start)",
    )
    args = ap.parse_args()

    if not (ASSETS / "idle").is_dir():
        print(
            "Assets not found. Run prepare_assets.py first:\n"
            "  python prepare_assets.py"
        )
        return 1

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    pet = DesktopPet(
        no_camera=args.no_camera,
        auto_start=not args.no_auto,
    )
    pet.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
