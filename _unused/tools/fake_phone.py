"""スマホの送信ページの代わり（テスト用）：待機して、ライブ表示を頼まれたら、その間だけ動画を高い fps で送る。

  /ctl/<id> に待機でつなぎ、{"cmd":"live_start"} が来たら /ws/<id>?mode=live に動画を流し、
  {"cmd":"live_stop"} が来たら止める。送信ページ（sender.html）と同じ動きを、動画ファイルでなぞる。
"""

import argparse
import asyncio
import json
import time

import websockets

from stream_video import packets_from_container


async def stream_live(url, path, fps_hint, stop_evt):
    async with websockets.connect(url, max_size=None) as ws:
        print(f"[live] 配信開始 {url}", flush=True)
        sent, start = 0, time.monotonic()
        while not stop_evt.is_set():
            base = time.monotonic()
            for t, data in packets_from_container(path):
                if stop_evt.is_set():
                    break
                delay = base + t - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                await ws.send(data)
                sent += 1
        print(f"[live] 配信停止（{sent} packets, {time.monotonic() - start:.1f}秒）", flush=True)


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--base", required=True, help="例: ws://ingest:8000")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--seconds", type=float, default=40, help="待機する時間の上限")
    args = ap.parse_args()

    stop_evt, task = asyncio.Event(), None
    async with websockets.connect(f"{args.base}/ctl/{args.camera}") as ctl:
        print(f"[ctl] 待機中 {args.base}/ctl/{args.camera}", flush=True)
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(ctl.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            m = json.loads(raw)
            print(f"[ctl] {m}", flush=True)
            if m.get("cmd") == "live_start" and (task is None or task.done()):
                stop_evt.clear()
                task = asyncio.create_task(stream_live(f"{args.base}/ws/{args.camera}?mode=live", args.video, m.get("fps"), stop_evt))
            elif m.get("cmd") == "live_stop":
                stop_evt.set()
        stop_evt.set()
        if task:
            await task


if __name__ == "__main__":
    asyncio.run(main())
