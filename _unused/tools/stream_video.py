"""動画ファイル（H.264）を、スマホが送るのと同じ形（Annex B のバイト列）で ingest に流す。再エンコードはしない。

例:
  python tools/stream_video.py data/videos/samples/people-walking.mp4 --url ws://ingest:8000/ws/SAMPLE-1
  python tools/stream_video.py clip.mp4 --url ws://localhost:8000/ws/SAMPLE-2 --loop --speed 2

- 実時間（--speed 1）で、フレームの時刻に合わせて送る。--ts-header を付けると、各メッセージの先頭に
  撮影時刻（epoch ミリ秒、8バイト）を付ける（ingest 側も ?ts_header=1 で受ける）。
- H.264 以外（HEVC の .mov など）は、先に ffmpeg で H.264 にしておく：
    ffmpeg -i in.mov -c:v libx264 -pix_fmt yuv420p out.mp4
"""

import argparse
import asyncio
import ssl
import struct
import sys
import time

import av
import websockets
from websockets.exceptions import ConnectionClosed


def packets_from_container(path):
    """(pts_seconds, annexb_bytes) を返す。MP4 の H.264 は Annex B に変換し、キーフレームに SPS/PPS を付ける。"""
    container = av.open(path)
    stream = container.streams.video[0]
    if stream.codec_context.name != "h264":
        sys.exit(f"H.264 ではありません（{stream.codec_context.name}）。ffmpeg で H.264 に変換してください。")
    bsf = av.bitstream.BitStreamFilterContext("h264_mp4toannexb", stream)
    base = None
    for packet in container.demux(stream):
        if packet.size == 0:
            continue
        for out in bsf.filter(packet):
            t = float(out.pts * stream.time_base) if out.pts is not None else None
            if t is None:
                continue
            base = t if base is None else base
            yield t - base, bytes(out)


async def listen(ws):
    """サーバーからの指示（ライブ表示で fps を上げる、など）を表示する。"""
    try:
        async for msg in ws:
            if isinstance(msg, str):
                print(f"[server] {msg}", flush=True)
    except Exception:
        pass


async def stream_once(ws, path, speed, ts_header):
    start = time.monotonic()
    sent = 0
    for t, data in packets_from_container(path):
        delay = start + t / speed - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if ts_header:
            data = struct.pack(">Q", int(time.time() * 1000)) + data
        await ws.send(data)
        sent += 1
    return sent


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--url", required=True, help="ws://<host>:8000/ws/<camera_id>")
    ap.add_argument("--speed", type=float, default=1.0, help="再生速度の倍率（1 = 実時間）")
    ap.add_argument("--loop", action="store_true", help="繰り返し流す")
    ap.add_argument("--ts-header", action="store_true", help="先頭に撮影時刻(8バイト)を付ける")
    ap.add_argument("--insecure", action="store_true", help="wss:// の自己署名証明書を検証しない（gateway 経由のテスト用）")
    args = ap.parse_args()

    url = args.url + ("&" if "?" in args.url else "?") + "ts_header=1" if args.ts_header else args.url
    ssl_ctx = None
    if url.startswith("wss://"):
        ssl_ctx = ssl.create_default_context()
        if args.insecure:
            ssl_ctx.check_hostname, ssl_ctx.verify_mode = False, ssl.CERT_NONE
    async with websockets.connect(url, max_size=None, ssl=ssl_ctx) as ws:
        print(f"[connected] {url}")
        listener = asyncio.create_task(listen(ws))
        n = 0
        while True:
            n += 1
            sent = await stream_once(ws, args.video, args.speed, args.ts_header)
            print(f"[sent] {sent} packets (pass {n})")
            if not args.loop:
                break
        await asyncio.sleep(1.0)  # パーサーに残った最後のフレームが出るのを待つ


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionClosed as e:
        sys.exit(f"[closed] code={e.rcvd.code if e.rcvd else None} reason={e.rcvd.reason if e.rcvd else ''}")
