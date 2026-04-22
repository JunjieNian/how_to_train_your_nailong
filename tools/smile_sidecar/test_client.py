#!/usr/bin/env python3
"""
test_client.py — sanity check for smile_sidecar/main.py.

Connects to ws://host:port, runs a scripted timeline:

    t=0.0s   connect, listen
    t=1.0s   start_calibration
    t=3.5s   end_calibration
    t=8.5s   reset
    t=10.5s  exit

Prints a one-line summary every second:
    [t=2.0s] 14 samples (face=12, smiling=0) avg_score=0.073 status=calibrating

Pass --print-raw to dump every sample/status JSON line as it arrives.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import time

import websockets


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=38751)
    ap.add_argument("--duration", type=float, default=10.5)
    ap.add_argument("--print-raw", action="store_true")
    args = ap.parse_args()

    uri = f"ws://{args.host}:{args.port}"
    print(f"[client] connecting to {uri}")
    async with websockets.connect(uri) as ws:
        t0 = time.monotonic()
        bucket: dict[int, dict] = collections.defaultdict(
            lambda: {"n": 0, "face": 0, "smile": 0, "score_sum": 0.0, "status": ""}
        )
        cur_status = "(initial)"

        async def reader() -> None:
            nonlocal cur_status
            async for raw in ws:
                if args.print_raw:
                    print("  <-", raw)
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = time.monotonic() - t0
                sec = int(t)
                b = bucket[sec]
                if msg.get("type") == "sample":
                    b["n"] += 1
                    if msg.get("face_found"):
                        b["face"] += 1
                    if msg.get("is_smiling"):
                        b["smile"] += 1
                    b["score_sum"] += float(msg.get("smile_score", 0.0))
                elif msg.get("type") == "status":
                    cur_status = msg.get("state", "?")
                    print(f"  <- status: {cur_status} baseline={msg.get('baseline')}")

        async def script() -> None:
            timeline = [
                (1.0, json.dumps({"cmd": "start_calibration"})),
                (3.5, json.dumps({"cmd": "end_calibration"})),
                (8.5, json.dumps({"cmd": "reset"})),
            ]
            for delay, payload in timeline:
                await asyncio.sleep(max(0.0, t0 + delay - time.monotonic()))
                print(f"  -> {payload}")
                await ws.send(payload)
            await asyncio.sleep(max(0.0, t0 + args.duration - time.monotonic()))

        async def reporter() -> None:
            for sec in range(1, int(args.duration) + 1):
                await asyncio.sleep(max(0.0, t0 + sec - time.monotonic()))
                b = bucket.get(sec - 1, {"n": 0, "face": 0, "smile": 0, "score_sum": 0.0})
                avg = (b["score_sum"] / b["n"]) if b["n"] else 0.0
                print(f"[t={sec}s] {b['n']:3d} samples (face={b['face']:2d}, smiling={b['smile']:2d}) "
                      f"avg_score={avg:.3f} status={cur_status}")

        try:
            await asyncio.wait(
                [asyncio.create_task(reader()),
                 asyncio.create_task(script()),
                 asyncio.create_task(reporter())],
                timeout=args.duration + 1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            print("[client] done")


if __name__ == "__main__":
    asyncio.run(main())
