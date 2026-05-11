"""
smile_detector.py — embedded MediaPipe smile detector running on a QThread.

Port of tools/smile_sidecar/main.py detection logic, adapted for in-process use.
Uses MediaPipe FaceLandmarker in VIDEO mode (synchronous per-frame) and emits
results via pyqtSignals to the GUI thread.

Smile score formula: 0.5 * (mouthSmileLeft + mouthSmileRight) + 0.2 * jawOpen
Calibration: collect raw scores, baseline = mean of bottom 90%
Sliding window: is_smiling if >= consecutive recent frames above threshold
"""

from __future__ import annotations

import collections
import logging
import time
import threading
from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("smile_detector")


@dataclass
class SmileSample:
    t: float              # monotonic time (seconds)
    face_found: bool
    smile_score: float    # baseline-subtracted, 0..1
    smile_score_raw: float
    is_smiling: bool      # sliding-window confirmed
    calibrated: bool


class SmileDetector(QThread):
    """Camera capture + MediaPipe face landmark detection on a background thread.

    Signals:
        sample_ready(SmileSample) — emitted every frame
        detector_ready()          — emitted on first valid face detection
        detector_lost(str)        — emitted on camera/model error
    """

    sample_ready = pyqtSignal(object)
    detector_ready = pyqtSignal()
    detector_lost = pyqtSignal(str)

    def __init__(
        self,
        camera_index: int = 0,
        model_path: str | None = None,
        fps: float = 15.0,
        parent=None,
    ):
        super().__init__(parent)
        self._camera_index = camera_index
        self._model_path = model_path
        self._fps = fps

        # Thread-safe controls
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._calibrating = False
        self._calibration_samples: list[float] = []
        self._baseline: float | None = None
        self._threshold: float = 0.28
        self._consecutive: int = 4
        self._recent_above: collections.deque[bool] = collections.deque(maxlen=8)
        self._ready_emitted = False

    # ── thread-safe control methods ────────────────────────────

    def start_calibration(self) -> None:
        with self._lock:
            self._calibrating = True
            self._calibration_samples.clear()

    def end_calibration(self) -> None:
        with self._lock:
            self._calibrating = False
            if self._calibration_samples:
                # Discard top 10% to ignore stray micro-smiles
                s = sorted(self._calibration_samples)
                cut = max(1, int(len(s) * 0.9))
                self._baseline = sum(s[:cut]) / cut

    def reset_state(self) -> None:
        with self._lock:
            self._baseline = None
            self._calibrating = False
            self._calibration_samples.clear()
            self._recent_above.clear()
            self._ready_emitted = False

    def set_threshold(self, v: float) -> None:
        with self._lock:
            self._threshold = v

    def set_consecutive(self, n: int) -> None:
        with self._lock:
            self._consecutive = n
            self._recent_above = collections.deque(
                self._recent_above, maxlen=max(n + 2, 6),
            )

    def request_stop(self) -> None:
        self._stop_flag.set()

    # ── detection loop ─────────────────────────────────────────

    def run(self) -> None:
        try:
            import cv2  # type: ignore
        except ImportError:
            self.detector_lost.emit("opencv-python not installed")
            return

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self.detector_lost.emit(f"Cannot open camera {self._camera_index}")
            return

        # Try to load MediaPipe
        landmarker = None
        if self._model_path:
            try:
                import mediapipe as mp  # type: ignore
                from mediapipe.tasks import python as mp_python  # type: ignore
                from mediapipe.tasks.python import vision  # type: ignore

                base = mp_python.BaseOptions(model_asset_path=self._model_path)
                opts = vision.FaceLandmarkerOptions(
                    base_options=base,
                    running_mode=vision.RunningMode.VIDEO,
                    num_faces=1,
                    output_face_blendshapes=True,
                    output_facial_transformation_matrixes=False,
                )
                landmarker = vision.FaceLandmarker.create_from_options(opts)
            except Exception as e:
                log.warning("MediaPipe init failed: %s", e)
                self.detector_lost.emit(f"MediaPipe init failed: {e}")
                cap.release()
                return
        else:
            self.detector_lost.emit("No model path provided")
            cap.release()
            return

        import mediapipe as mp  # type: ignore

        period = 1.0 / self._fps
        next_t = time.monotonic()

        while not self._stop_flag.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(time.monotonic() * 1000)

            try:
                result = landmarker.detect_for_video(mp_image, ts_ms)
            except Exception:
                continue

            face_found = bool(result.face_blendshapes)
            if face_found:
                score_raw, _ = self._score_from_blendshapes(
                    result.face_blendshapes[0],
                )
            else:
                score_raw = 0.0

            with self._lock:
                if self._calibrating and face_found:
                    self._calibration_samples.append(score_raw)

                baseline = self._baseline
                score = max(0.0, score_raw - baseline) if baseline is not None else score_raw

                above = face_found and score > self._threshold
                self._recent_above.append(above)
                is_smiling = (
                    face_found
                    and baseline is not None
                    and sum(self._recent_above) >= self._consecutive
                )
                calibrated = baseline is not None
                ready_emitted = self._ready_emitted

            sample = SmileSample(
                t=time.monotonic(),
                face_found=face_found,
                smile_score=score,
                smile_score_raw=score_raw,
                is_smiling=is_smiling,
                calibrated=calibrated,
            )
            self.sample_ready.emit(sample)

            if face_found and not ready_emitted:
                with self._lock:
                    self._ready_emitted = True
                self.detector_ready.emit()

            # Maintain target FPS
            next_t += period
            sleep_time = next_t - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_t = time.monotonic()

        cap.release()
        if landmarker:
            landmarker.close()

    # ── blendshape scoring ─────────────────────────────────────

    @staticmethod
    def _score_from_blendshapes(blendshapes) -> tuple[float, dict[str, float]]:
        """Combine blendshapes into a single smile score in [0, 1].

        Formula: 0.5 * (mouthSmileLeft + mouthSmileRight) + 0.2 * jawOpen
        """
        wanted = {"mouthSmileLeft", "mouthSmileRight", "jawOpen"}
        picked: dict[str, float] = {}
        for cat in blendshapes:
            if cat.category_name in wanted:
                picked[cat.category_name] = float(cat.score)
        sl = picked.get("mouthSmileLeft", 0.0)
        sr = picked.get("mouthSmileRight", 0.0)
        jo = picked.get("jawOpen", 0.0)
        score = 0.5 * (sl + sr) + 0.2 * jo
        return min(1.0, max(0.0, score)), picked
