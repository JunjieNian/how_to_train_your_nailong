#!/usr/bin/env python3
"""
smile_sidecar — MediaPipe-based smile detector that streams JSON over WebSocket.

Architecture:
    [cv2 capture thread] -> frame queue -> [MediaPipe live-stream callback] ->
        score buffer -> [WebSocket broadcast loop on asyncio]

Wire protocol (JSON, newline-free, one message per ws frame):

  Sample (sidecar -> client):
    {"type":"sample","t":<int ms>,"face_found":<bool>,
     "smile_score":<float 0..1>,"smile_score_raw":<float 0..1>,
     "is_smiling":<bool>,"calibrated":<bool>,
     "blendshapes":{"mouthSmileLeft":..,"mouthSmileRight":..,"jawOpen":..}}

  Status (sidecar -> client):
    {"type":"status","state":"idle|calibrating|running","baseline":<float|null>,"fps":<float>}

  Command (client -> sidecar):
    {"cmd":"start_calibration"}        — begin recording neutral baseline (~2.5s)
    {"cmd":"end_calibration"}          — stop calibration early; freeze baseline
    {"cmd":"reset"}                    — drop baseline, return to uncalibrated
    {"cmd":"set_threshold","value":0.28}
    {"cmd":"set_consecutive","value":4}

Run:
    pip install -r requirements.txt
    # download the model once:
    curl -L -o face_landmarker.task \
        https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task

    # production: read from a real webcam
    python3 main.py --model face_landmarker.task --port 38751 --camera 0

    # dev: feed a video file or still image (loops at --fps regardless of native rate)
    python3 main.py --model face_landmarker.task --source /path/to/face_clip.mp4
    python3 main.py --model face_landmarker.task --source /path/to/selfie.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("smile_sidecar")


# ---------- shared state ----------------------------------------------------

@dataclass
class DetectorState:
    threshold: float = 0.28
    consecutive: int = 4
    baseline: float | None = None        # neutral smile score recorded during calibration
    calibrating: bool = False
    calibration_samples: list[float] = field(default_factory=list)
    recent_above: collections.deque[bool] = field(default_factory=lambda: collections.deque(maxlen=8))

    def reset(self) -> None:
        self.baseline = None
        self.calibrating = False
        self.calibration_samples.clear()
        self.recent_above.clear()


# ---------- mediapipe wrapper ----------------------------------------------

def make_landmarker(model_path: Path, on_result):
    """Construct a MediaPipe FaceLandmarker in LIVE_STREAM mode."""
    import mediapipe as mp  # type: ignore
    from mediapipe.tasks import python as mp_python  # type: ignore
    from mediapipe.tasks.python import vision  # type: ignore

    base = mp_python.BaseOptions(model_asset_path=str(model_path))
    opts = vision.FaceLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.LIVE_STREAM,
        num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=False,
        result_callback=on_result,
    )
    return vision.FaceLandmarker.create_from_options(opts)


def smile_score_from_blendshapes(blendshapes) -> tuple[float, dict[str, float]]:
    """Combine MediaPipe blendshape categories into a single smile score in [0, 1].

    Weights are an MVP starting point — tune per detector / camera.
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


# ---------- broadcast bus ---------------------------------------------------

class Bus:
    """Asyncio fan-out from sync detector callback to all connected websockets."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        self.clients: set[Any] = set()

    def push_threadsafe(self, payload: dict) -> None:
        msg = json.dumps(payload, separators=(",", ":"))
        try:
            self.loop.call_soon_threadsafe(self._enqueue, msg)
        except RuntimeError:
            pass  # loop closed during shutdown

    def _enqueue(self, msg: str) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(msg)

    async def fanout(self) -> None:
        while True:
            msg = await self.queue.get()
            dead = []
            for ws in self.clients:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)


# ---------- capture thread --------------------------------------------------

def capture_loop(
    camera_index: int,
    source_path: str | None,
    target_fps: float,
    landmarker,
    started: threading.Event,
    stop: threading.Event,
) -> None:
    """Capture frames from a webcam (camera_index >= 0) or a file (source_path).

    File mode is meant for development on machines without a webcam; the file
    is looped indefinitely at target_fps regardless of its native frame rate.
    Single images are also accepted (one frame is re-emitted on every tick).
    """
    import cv2  # type: ignore
    import mediapipe as mp  # type: ignore

    is_image = False
    static_frame = None
    if source_path is not None:
        cap = cv2.VideoCapture(source_path)
        if not cap.isOpened():
            # Try as a still image
            static_frame = cv2.imread(source_path)
            if static_frame is None:
                log.error("cannot open source %s", source_path)
                return
            is_image = True
            log.info("source = still image %s (%dx%d)",
                     source_path, static_frame.shape[1], static_frame.shape[0])
        else:
            log.info("source = video file %s", source_path)
    else:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            log.error("cannot open camera %d", camera_index)
            return
        cap.set(cv2.CAP_PROP_FPS, target_fps)
        log.info("source = camera %d", camera_index)
    started.set()

    period = 1.0 / target_fps
    next_t = time.monotonic()
    log.info("capture started @ %.1f FPS", target_fps)

    while not stop.is_set():
        if is_image:
            frame = static_frame.copy()
            ok = True
        else:
            ok, frame = cap.read()
            if not ok and source_path is not None:
                # End of file → loop back to first frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
        if not ok:
            time.sleep(0.05)
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms = int(time.monotonic() * 1000)
        try:
            landmarker.detect_async(mp_image, ts_ms)
        except Exception as e:  # pragma: no cover
            log.warning("detect_async failed: %s", e)

        next_t += period
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
        else:
            next_t = time.monotonic()  # we're behind, drop the schedule

    if not is_image:
        cap.release()
    log.info("capture stopped")


# ---------- main ------------------------------------------------------------

async def serve(args: argparse.Namespace) -> None:
    import websockets

    loop = asyncio.get_running_loop()
    bus = Bus(loop)
    state = DetectorState(threshold=args.threshold, consecutive=args.consecutive)

    def on_result(result, _image, ts_ms: int) -> None:
        face_found = bool(result.face_blendshapes)
        if face_found:
            score_raw, picked = smile_score_from_blendshapes(result.face_blendshapes[0])
        else:
            score_raw, picked = 0.0, {}

        if state.calibrating and face_found:
            state.calibration_samples.append(score_raw)

        if state.baseline is not None:
            score = max(0.0, score_raw - state.baseline)
        else:
            score = score_raw

        above = face_found and score > state.threshold
        state.recent_above.append(above)
        is_smiling = (
            face_found
            and state.baseline is not None
            and sum(state.recent_above) >= state.consecutive
        )

        bus.push_threadsafe({
            "type": "sample",
            "t": ts_ms,
            "face_found": face_found,
            "smile_score": round(score, 4),
            "smile_score_raw": round(score_raw, 4),
            "is_smiling": is_smiling,
            "calibrated": state.baseline is not None,
            "blendshapes": {k: round(v, 4) for k, v in picked.items()},
        })

    started = threading.Event()
    stop = threading.Event()

    if args.mock_detector:
        # Synthetic signal: smile_score = 0.5 + 0.4*sin(2π·t/period). Useful for
        # smoke-testing the WebSocket protocol without MediaPipe / a real face.
        import math

        def mock_loop():
            log.info("source = MOCK detector (sine, period=%.1fs)", args.mock_period)
            started.set()
            period = 1.0 / args.fps
            next_t = time.monotonic()
            t0 = time.monotonic()
            while not stop.is_set():
                t = time.monotonic() - t0
                score_raw = 0.5 + 0.4 * math.sin(2 * math.pi * t / args.mock_period)
                ts_ms = int(time.monotonic() * 1000)
                # Hand-write a synthetic on_result-equivalent payload.
                if state.calibrating:
                    state.calibration_samples.append(score_raw)
                score = max(0.0, score_raw - state.baseline) if state.baseline is not None else score_raw
                above = score > state.threshold
                state.recent_above.append(above)
                is_smiling = (
                    state.baseline is not None
                    and sum(state.recent_above) >= state.consecutive
                )
                bus.push_threadsafe({
                    "type": "sample",
                    "t": ts_ms,
                    "face_found": True,
                    "smile_score": round(score, 4),
                    "smile_score_raw": round(score_raw, 4),
                    "is_smiling": is_smiling,
                    "calibrated": state.baseline is not None,
                    "blendshapes": {"mouthSmileLeft": round(score_raw, 4),
                                    "mouthSmileRight": round(score_raw, 4),
                                    "jawOpen": 0.0},
                    "mock": True,
                })
                next_t += period
                sleep = next_t - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
                else:
                    next_t = time.monotonic()
            log.info("mock detector stopped")

        cap_thread = threading.Thread(target=mock_loop, daemon=True)
    else:
        landmarker = make_landmarker(Path(args.model), on_result)
        cap_thread = threading.Thread(
            target=capture_loop,
            args=(args.camera, args.source, args.fps, landmarker, started, stop),
            daemon=True,
        )

    cap_thread.start()
    if not started.wait(timeout=5.0):
        log.error("capture thread failed to start within 5s")
        sys.exit(1)

    async def handle_client(ws) -> None:
        bus.clients.add(ws)
        log.info("client connected (%d total)", len(bus.clients))
        try:
            await ws.send(json.dumps({
                "type": "status", "state": "ready",
                "baseline": state.baseline, "fps": args.fps,
            }))
            async for msg in ws:
                try:
                    cmd = json.loads(msg)
                except Exception:
                    continue
                kind = cmd.get("cmd")
                if kind == "start_calibration":
                    state.calibrating = True
                    state.calibration_samples.clear()
                    await ws.send(json.dumps({"type": "status", "state": "calibrating"}))
                elif kind == "end_calibration":
                    state.calibrating = False
                    if state.calibration_samples:
                        # discard top 10% to ignore stray micro-smiles during calibration
                        s = sorted(state.calibration_samples)
                        cut = max(1, int(len(s) * 0.9))
                        state.baseline = sum(s[:cut]) / cut
                    await ws.send(json.dumps({
                        "type": "status", "state": "running",
                        "baseline": state.baseline,
                    }))
                elif kind == "reset":
                    state.reset()
                    await ws.send(json.dumps({"type": "status", "state": "ready", "baseline": None}))
                elif kind == "set_threshold":
                    state.threshold = float(cmd.get("value", state.threshold))
                elif kind == "set_consecutive":
                    state.consecutive = int(cmd.get("value", state.consecutive))
                    state.recent_above = collections.deque(state.recent_above, maxlen=max(state.consecutive + 2, 6))
        finally:
            bus.clients.discard(ws)
            log.info("client gone (%d total)", len(bus.clients))

    fanout_task = asyncio.create_task(bus.fanout())
    server = await websockets.serve(handle_client, args.host, args.port)
    log.info("listening on ws://%s:%d", args.host, args.port)

    try:
        await server.wait_closed()
    finally:
        stop.set()
        fanout_task.cancel()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None,
                    help="path to face_landmarker.task (required unless --mock-detector)")
    ap.add_argument("--camera", type=int, default=0,
                    help="webcam index (ignored if --source or --mock-detector is given)")
    ap.add_argument("--source", default=None,
                    help="path to a video file or still image to use instead of a webcam (dev mode)")
    ap.add_argument("--mock-detector", action="store_true",
                    help="emit synthetic smile_score sin-wave samples without using MediaPipe / a camera")
    ap.add_argument("--mock-period", type=float, default=4.0,
                    help="period (seconds) of the mock-detector smile_score sine wave")
    ap.add_argument("--fps", type=float, default=15.0, help="target capture FPS")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=38751)
    ap.add_argument("--threshold", type=float, default=0.28)
    ap.add_argument("--consecutive", type=int, default=4)
    ap.add_argument("--log", default="INFO")
    args = ap.parse_args()

    if not args.mock_detector and not args.model:
        ap.error("--model is required unless --mock-detector is set")

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        log.info("interrupted")


if __name__ == "__main__":
    main()
