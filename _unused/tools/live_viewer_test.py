"""管理画面の代わり（テスト用）：ライブ中継（WebSocket）を受け取り、届いた H.264 がデコードできるか確かめる。

  python live_viewer_test.py --url ws://backend:8080/api/live/SAMPLE-1 --seconds 8
ブラウザの VideoDecoder の代わりに PyAV でデコードして、フレーム数と、届いた速さを数える。
"""

import argparse
import asyncio
import time

import av
import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--seconds", type=float, default=8)
    args = ap.parse_args()

    chunks, arrivals = [], []
    t0 = time.monotonic()
    async with websockets.connect(args.url, max_size=None) as ws:
        while time.monotonic() - t0 < args.seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                chunks.append(msg)
                arrivals.append(time.monotonic() - t0)

    total = sum(len(c) for c in chunks)
    print(f"受け取ったチャンク {len(chunks)} 個 / {args.seconds:.0f}秒（{len(chunks) / args.seconds:.1f}/秒）、{total // 1024} KB（{total * 8 / args.seconds / 1e6:.2f} Mbps）")
    if arrivals:
        print(f"最初のチャンクまで {arrivals[0]:.2f} 秒（見始めてから）")

    # PyAV でデコードしてみる（ブラウザの VideoDecoder の代わり）。キーフレームから始まっていなければ、先頭は読めない
    ctx = av.CodecContext.create("h264", "r")
    frames, errors = 0, 0
    for c in chunks:
        try:
            for pkt in ctx.parse(c):
                frames += len(ctx.decode(pkt))
        except av.error.FFmpegError:
            errors += 1
    print(f"デコードできたフレーム {frames} 枚（チャンク {len(chunks)} 個のうち）、エラー {errors}")


asyncio.run(main())
