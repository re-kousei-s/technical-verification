"""ingest：H.264 のストリームを受け取り、デコードして、間引いたフレームをキューに積む。

接続
  WebSocket  ws://<host>:8000/ws/<camera_id>[?ts_header=1]
    - バイナリメッセージ = H.264 の Annex B（スタートコード付き）のバイト列。
      1メッセージに複数フレームが入っても、NAL の途中で切れていてもよい（パーサーが繋ぐ）
    - ts_header=1 のとき、各メッセージの先頭 8 バイトが撮影時刻（Unix epoch ミリ秒、ビッグエンディアン）。
      無いときはサーバーの受信時刻を使う
    - SPS/PPS を含めること（キーフレームごとに入れておけば、途中から繋いでも復帰できる）
    - 接続は camera_id ごとに1本まで。configs/cameras.yaml に無い camera_id は拒否する

処理
  全フレームをデコード（H.264 は前のフレームに依存するため間引けない）→ そのカメラの sample_fps で間引き
  → JPEG にして Redis Streams（frames:p{n}）に積む。n は camera_id のハッシュ（= 担当 worker が固定される）。
  キューが MAX_QUEUE を超えたら新しいフレームを捨てて、dropped に数える（worker が追いつかない目印）。

スマホ向けの送信ページと、端末の登録 API も持つ（ブラウザから直接使う）
  GET    /                     送信ページ（スマホで開く。カメラを使うには HTTPS が必要 → gateway 経由）
  GET    /api/floors           フロアごとの登録端末の一覧
  POST   /api/register         端末を登録  {"floor": 2, "name": "階段A"} → camera_id が払い出される
  GET    /api/cameras/{id}     端末の設定と、受信・カウントの状況、フロア人数の概算
  GET    /api/cameras/{id}/result  最新の認識結果（検出枠・追跡ID・最近の通過）。送信ページが重ねて表示する
  PATCH  /api/cameras/{id}     カウントライン {"line": [[x1,y1],[x2,y2]]} と処理fps {"sample_fps": 2} の変更
  POST   /api/cameras/{id}/reset   この端末の IN/OUT の履歴と累計を消す（フロア人数の概算は変えない）
  POST   /api/detect-gates     画像（image/jpeg）から、ドア・エレベーターなどの四角の候補を探す
  POST   /api/reset-all        全部リセット：全端末の IN/OUT の履歴と、全フロアの人数の概算を消す
  DELETE /api/cameras/{id}     登録解除（送信中は不可）
認証はない（検証用。LAN の中だけで使うこと）。
"""

import asyncio
import json
import logging
import os
import secrets
import struct
import time
from pathlib import Path

import av
import cv2
import numpy as np
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common.quads import detect_quads
from common.live import (DEFAULT_LINE, db_connect, estimate_margin, load_cameras, load_estimate, load_live_params, now_ms, partition_of,
                         reset_all, reset_history, stream_name)

log = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "200"))  # パーティションごとのキューの上限（フレーム数）
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))
SAMPLE_TOLERANCE = 0.02  # 秒。間引きの時刻が少し早くても採る（30fps なら1フレーム以内）

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="ingest")
redis_client = aioredis.from_url(REDIS_URL)
active = set()  # 接続中の camera_id
active_mode = {}  # camera_id -> "send"（認識する通常の送信）/ "live"（ダッシュボードのライブ表示のための、プレビュー専用の送信）
ctl_clients = {}  # camera_id -> 待機用（制御）の WebSocket


class H264Decoder:
    """Annex B のバイト列を流し込むと、デコードできたフレームが出てくる。"""

    def __init__(self):
        self.ctx = av.CodecContext.create("h264", "r")
        self.errors = 0

    def feed(self, data):
        frames = []
        try:
            packets = self.ctx.parse(data)
        except av.error.FFmpegError:
            self.errors += 1
            return frames
        for pkt in packets:
            try:
                frames.extend(self.ctx.decode(pkt))
            except av.error.FFmpegError:
                # 途中から繋いだときや、パケットが欠けたとき。次のキーフレームで復帰する
                self.errors += 1
        return frames


def process_chunk(decoder, state, data, chunk_ts, fps, live=None, recognize=True):
    """デコードして、(1) 間引きに該当するフレームを認識用の JPEG に、(2) ライブ表示中なら全フレームを表示用の小さい JPEG に。
    スレッドで動かす（CPU 処理）。live は None（表示する人がいない）か {"width": 幅, "quality": 品質}。"""
    out, live_out = [], []
    frames = decoder.feed(data)
    interval = 1.0 / fps
    for frame in frames:
        state["decoded"] += 1
        want_sample = recognize and not (state["last_sampled"] is not None and chunk_ts - state["last_sampled"] < interval - SAMPLE_TOLERANCE)
        if not want_sample and live is None:
            continue
        img = frame.to_ndarray(format="bgr24")
        if live is not None:
            small = img
            if img.shape[1] > live["width"]:
                small = cv2.resize(img, (live["width"], round(img.shape[0] * live["width"] / img.shape[1])), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, live["quality"]])
            if ok:
                live_out.append(buf.tobytes())
        if want_sample:
            state["last_sampled"] = chunk_ts
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                out.append((img.shape[1], img.shape[0], buf.tobytes()))
    return len(frames), out, live_out


async def _live_control(ws, camera_id, live_state, params):
    """ダッシュボードがライブ表示を見ている間だけ、端末に高い fps で送るよう頼む（見終わったら戻す）。"""
    sent = None
    while True:
        try:
            on = bool(await redis_client.exists(f"liveview:{camera_id}"))
            live_state["on"] = on
            want = params["live_fps"] if on else params["normal_fps"]
            if want != sent:
                await ws.send_text(json.dumps({"send_fps": want, "live": on}))
                log.info("send_fps %s -> %s (live=%s)", camera_id, want, on)
                sent = want
        except Exception:
            return          # 接続が閉じた
        await asyncio.sleep(0.5)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_heartbeat())


async def _heartbeat():
    while True:
        try:
            await redis_client.set("ingest:heartbeat", now_ms(), ex=15)
        except Exception as e:  # redis が落ちていても、復帰したら続ける
            log.warning("heartbeat failed: %s", e)
        await asyncio.sleep(5)


@app.get("/healthz")
async def healthz():
    await redis_client.ping()
    return {"ok": True, "active": sorted(active)}


@app.websocket("/ws/{camera_id}")
async def ws_camera(ws: WebSocket, camera_id: str, ts_header: int = Query(0), mode: str = Query("send")):
    cameras = await asyncio.to_thread(load_cameras)  # 接続のたびに読む（端末の登録・fps の変更を再起動なしで反映）
    await ws.accept()
    if camera_id not in cameras:
        await ws.close(code=4404, reason=f"unknown camera_id: {camera_id}")
        return
    if camera_id in active:
        await ws.close(code=4409, reason="camera already streaming")
        return
    active.add(camera_id)
    mode = "live" if mode == "live" else "send"
    active_mode[camera_id] = mode
    recognize = mode == "send"      # live は、ライブ表示のためだけの送信。認識・カウントには使わない

    cam = cameras[camera_id]
    fps = float(cam["sample_fps"])
    partition = partition_of(camera_id)
    stream = stream_name(partition)
    key = f"cam:{camera_id}"
    decoder = H264Decoder()
    state = {"decoded": 0, "last_sampled": None}
    live_params = load_live_params()
    live_state = {"on": not recognize}      # プレビュー専用の送信は、常に表示用の JPEG を流す
    # 通常の送信だけ、ライブ表示の間は端末に高い fps を頼む（プレビュー専用の送信は、最初から高い fps で来る）
    control_task = asyncio.create_task(_live_control(ws, camera_id, live_state, live_params)) if recognize else None
    rate = {"t": time.time(), "n": 0}
    enqueued = dropped = 0
    t_connect = time.time()
    await redis_client.hset(key, mapping={
        "connected": 1 if recognize else 0, "live_streaming": 0 if recognize else 1, "mode": mode,
        "connected_at_ms": now_ms(), "sample_fps": fps, "partition": partition,
        "decoded": 0, "enqueued": 0, "dropped": 0, "decode_errors": 0,
    })
    log.info("connected %s (mode=%s, sample_fps=%s, partition=%s, ts_header=%s)", camera_id, mode, fps, partition, ts_header)

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue  # テキスト（ping など）は無視
            if ts_header:
                if len(data) < 8:
                    continue
                chunk_ts = struct.unpack(">Q", data[:8])[0] / 1000.0
                data = data[8:]
            else:
                chunk_ts = time.time()

            live = {"width": live_params["width"], "quality": live_params["jpeg_quality"]} if live_state["on"] else None
            n_frames, jpegs, live_jpegs = await asyncio.to_thread(process_chunk, decoder, state, data, chunk_ts, fps, live, recognize)

            pipe = redis_client.pipeline()
            for jpeg in live_jpegs:
                pipe.publish(f"livejpeg:{camera_id}", jpeg)
            now = time.time()
            if now - rate["t"] >= 1.0:       # 受信しているフレームレートの実測（ダッシュボードのライブ表示に出す）
                pipe.hset(key, "rx_fps", round((state["decoded"] - rate["n"]) / (now - rate["t"]), 1))
                rate["t"], rate["n"] = now, state["decoded"]
            for w, h, jpeg in jpegs:
                if await redis_client.xlen(stream) >= MAX_QUEUE:
                    dropped += 1
                    continue
                pipe.xadd(stream, {
                    "camera_id": camera_id, "ts_ms": int(chunk_ts * 1000), "w": w, "h": h,
                    "enq_ms": now_ms(), "jpeg": jpeg,
                })
                enqueued += 1
            pipe.hset(key, mapping={
                "last_seen_ms": now_ms(), "decoded": state["decoded"], "enqueued": enqueued,
                "dropped": dropped, "decode_errors": decoder.errors,
                **({"w": jpegs[-1][0], "h": jpegs[-1][1]} if jpegs else {}),
            })
            await pipe.execute()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("stream error: %s", camera_id)
    finally:
        if control_task:
            control_task.cancel()
        active.discard(camera_id)
        active_mode.pop(camera_id, None)
        await redis_client.hset(key, mapping={"connected": 0, "live_streaming": 0, "disconnected_at_ms": now_ms()})
        log.info("disconnected %s: decoded=%d enqueued=%d dropped=%d errors=%d (%.0fs)",
                 camera_id, state["decoded"], enqueued, dropped, decoder.errors, time.time() - t_connect)


@app.websocket("/ctl/{camera_id}")
async def ws_control(ws: WebSocket, camera_id: str):
    """スマホの送信ページが、開いている間ずっとつなぐ待機用の接続。映像は流れない。

    ダッシュボードがライブ表示を開いたとき、端末がまだ送信していなければ、ここから「配信を始めて」と頼む
    （端末は /ws/<id>?mode=live で、プレビュー専用の映像を送ってくる）。閉じられたら「止めて」と頼む。
    """
    cameras = await asyncio.to_thread(load_cameras)
    await ws.accept()
    if camera_id not in cameras:
        await ws.close(code=4404, reason=f"unknown camera_id: {camera_id}")
        return
    old = ctl_clients.get(camera_id)
    if old is not None:
        try:
            await old.close(code=4410, reason="replaced by a newer page")
        except Exception:
            pass
    ctl_clients[camera_id] = ws
    params = load_live_params()
    log.info("control connected %s", camera_id)

    async def watch():
        asked_at = None          # 「配信を始めて」と頼んだ時刻（頼んでいなければ None）
        while True:
            await redis_client.set(f"ctl:{camera_id}", 1, ex=4)          # 待機している端末がある、という印（ダッシュボードが見る）
            on = bool(await redis_client.exists(f"liveview:{camera_id}"))
            streaming = camera_id in active
            mode = active_mode.get(camera_id)
            if on and not streaming and (asked_at is None or time.time() - asked_at > 6):
                await ws.send_text(json.dumps({"cmd": "live_start", "fps": params["live_fps"]}))   # 頼んで6秒たっても始まらなければ、もう一度
                asked_at = time.time()
            elif not on and asked_at is not None:
                await ws.send_text(json.dumps({"cmd": "live_stop"}))
                asked_at = None
            elif asked_at is not None and streaming and mode == "send":
                asked_at = None      # 見ている間に、端末が通常の送信を始めた。止めてもらう必要はない
            await asyncio.sleep(0.5)

    task = asyncio.create_task(watch())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("control error: %s", camera_id)
    finally:
        task.cancel()
        if ctl_clients.get(camera_id) is ws:
            del ctl_clients[camera_id]
            await redis_client.delete(f"ctl:{camera_id}")
        log.info("control disconnected %s", camera_id)


# ---------------------------------------------------------------------------
# 送信ページと、端末の登録 API
# ---------------------------------------------------------------------------

class Register(BaseModel):
    floor: int = Field(ge=-9, le=99)
    name: str = Field("", max_length=30)


class Gate(BaseModel):
    id: str = Field(max_length=24)
    name: str = Field(max_length=30)
    kind: str = "door"                    # elevator / stairs / door
    quad: list[list[float]]               # [左上, 右上, 右下, 左下]（割合）


class CameraPatch(BaseModel):
    line: list[list[float]] | None = None
    sample_fps: float | None = Field(None, ge=0.5, le=10)
    gates: list[Gate] | None = Field(None, max_length=12)


def _validate_line(line):
    if len(line) != 2 or any(len(p) != 2 or not all(0.0 <= v <= 1.0 for v in p) for p in line):
        raise HTTPException(422, "line は [[x1,y1],[x2,y2]]（各 0〜1）で指定する")
    (x1, y1), (x2, y2) = line
    if (x2 - x1) ** 2 + (y2 - y1) ** 2 < 0.05 ** 2:
        raise HTTPException(422, "線が短すぎる")
    return [[round(x1, 4), round(y1, 4)], [round(x2, 4), round(y2, 4)]]


def _validate_gate(g):
    if g.kind not in ("elevator", "stairs", "door"):
        raise HTTPException(422, "kind は elevator / stairs / door")
    if len(g.quad) != 4 or any(len(p) != 2 or not all(-0.05 <= v <= 1.05 for v in p) for p in g.quad):
        raise HTTPException(422, "quad は 4 点 [[x,y],...]（各 0〜1）で指定する")
    xs, ys = [p[0] for p in g.quad], [p[1] for p in g.quad]
    if (max(xs) - min(xs)) < 0.02 or (max(ys) - min(ys)) < 0.02:
        raise HTTPException(422, "ゲートが小さすぎる")
    return {"id": g.id, "name": g.name.strip() or "入口", "kind": g.kind,
            "quad": [[round(min(1.0, max(0.0, x)), 4), round(min(1.0, max(0.0, y)), 4)] for x, y in g.quad]}


def _public(cam):
    return {k: cam.get(k) for k in ("id", "floor", "name", "line", "gates", "sample_fps", "tracker", "anchor", "source")}


def _db_query(sql, args=(), fetch="all"):
    with db_connect(row_factory=dict_row) as conn:
        cur = conn.execute(sql, args)
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
        return cur.rowcount


@app.get("/")
@app.get("/sender")
async def sender_page():
    return FileResponse(STATIC / "sender.html", headers={"Cache-Control": "no-store"})


@app.get("/api/floors")
async def api_floors():
    cams = await asyncio.to_thread(load_cameras)
    floors = {}
    for c in cams.values():
        floors.setdefault(c["floor"], []).append(
            {**_public(c), "connected": c["id"] in active})
    return [{"floor": f, "devices": floors[f]} for f in sorted(floors)]


@app.post("/api/register")
async def api_register(body: Register):
    name = body.name.strip()
    cam_id = f"F{body.floor}-{secrets.token_hex(2).upper()}"
    await asyncio.to_thread(
        _db_query,
        "INSERT INTO cameras (camera_id, floor, name, line) VALUES (%s, %s, %s, %s)",
        (cam_id, body.floor, name or None, Jsonb(DEFAULT_LINE)), "none",
    )
    log.info("registered %s (floor=%s, name=%s)", cam_id, body.floor, name)
    return _public((await asyncio.to_thread(load_cameras))[cam_id])


async def _get_camera(camera_id):
    cam = (await asyncio.to_thread(load_cameras)).get(camera_id)
    if cam is None:
        raise HTTPException(404, "登録されていない端末")
    return cam


@app.get("/api/cameras/{camera_id}")
async def api_camera(camera_id: str):
    cam = await _get_camera(camera_id)
    live = {k.decode(): v.decode() for k, v in (await redis_client.hgetall(f"cam:{camera_id}")).items()}
    state = await asyncio.to_thread(
        _db_query, "SELECT in_count, out_count FROM camera_state WHERE camera_id = %s", (camera_id,), "one")
    floor_est = await asyncio.to_thread(_floor_estimate, cam["floor"])
    gate_rows = await asyncio.to_thread(
        _db_query, "SELECT gate, direction, count(*) AS n FROM crossings WHERE camera_id = %s AND gate IS NOT NULL "
                   "GROUP BY gate, direction", (camera_id,))
    gate_counts = {}
    for r in gate_rows:
        gate_counts.setdefault(r["gate"], {"in": 0, "out": 0})[r["direction"]] = r["n"]
    return {
        **_public(cam), "connected": camera_id in active,
        "server": {k: int(live.get(k, 0)) for k in ("decoded", "enqueued", "dropped", "decode_errors")},
        "in": state["in_count"] if state else 0, "out": state["out_count"] if state else 0,
        "floor_estimate": floor_est, "gate_counts": gate_counts,
    }


def _floor_estimate(floor):
    """フロア人数の概算と範囲（dashboard と同じ式）。"""
    row = _db_query("SELECT count, corrected_at FROM floor_counts WHERE floor = %s", (floor,), "one")
    count = row["count"] if row else 0
    since = row["corrected_at"] if row else None
    n = _db_query(
        "SELECT count(*) AS n FROM crossings WHERE floor = %s AND (%s::timestamptz IS NULL OR ts > %s)",
        (floor, since, since), "one")["n"]
    margin = estimate_margin(n, load_estimate()["error_rate"])
    return {"count": count, "low": max(0, count - margin), "high": count + margin, "crossings": n}


@app.get("/api/cameras/{camera_id}/result")
async def api_camera_result(camera_id: str):
    """最新の認識結果。送信中でなければ空（boxes なし）。"""
    raw = await redis_client.get(f"result:{camera_id}")
    if raw is None:
        return {"boxes": [], "events": [], "stale": True}
    return Response(content=raw, media_type="application/json")


@app.patch("/api/cameras/{camera_id}")
async def api_patch_camera(camera_id: str, body: CameraPatch):
    cam = await _get_camera(camera_id)
    if cam["source"] != "db":
        raise HTTPException(409, "yaml で固定したカメラは、ここでは変更できない")
    if body.line is not None:
        line = _validate_line(body.line)
        await asyncio.to_thread(
            _db_query, "UPDATE cameras SET line = %s, updated_at = now() WHERE camera_id = %s",
            (Jsonb(line), camera_id), "none")
    if body.gates is not None:
        gates = [_validate_gate(g) for g in body.gates]
        await asyncio.to_thread(
            _db_query, "UPDATE cameras SET gates = %s, updated_at = now() WHERE camera_id = %s",
            (Jsonb(gates), camera_id), "none")
    if body.sample_fps is not None:
        await asyncio.to_thread(
            _db_query, "UPDATE cameras SET sample_fps = %s, updated_at = now() WHERE camera_id = %s",
            (body.sample_fps, camera_id), "none")
    return _public((await asyncio.to_thread(load_cameras))[camera_id])


@app.delete("/api/cameras/{camera_id}")
async def api_delete_camera(camera_id: str):
    cam = await _get_camera(camera_id)
    if cam["source"] != "db":
        raise HTTPException(409, "yaml で固定したカメラは、ここでは削除できない")
    if camera_id in active:
        raise HTTPException(409, "送信中は削除できない。先に停止する")
    await asyncio.to_thread(_db_query, "DELETE FROM cameras WHERE camera_id = %s", (camera_id,), "none")
    log.info("unregistered %s", camera_id)
    return {"ok": True}


@app.post("/api/cameras/{camera_id}/reset")
async def api_reset_camera(camera_id: str):
    await _get_camera(camera_id)

    def run():
        with db_connect() as conn:
            return reset_history(conn, camera_id=camera_id)
    n = await asyncio.to_thread(run)
    log.info("reset history %s (crossings deleted: %d)", camera_id, n)
    return {"deleted_crossings": n}


@app.post("/api/reset-all")
async def api_reset_all():
    def run():
        with db_connect() as conn:
            return reset_all(conn)
    result = await asyncio.to_thread(run)
    log.warning("RESET ALL: %s", result)
    return result


@app.post("/api/detect-gates")
async def api_detect_gates(request: Request):
    """送信ページが撮った1枚の画像（JPEG）から、ドアらしい四角の候補を返す。候補は人が確認して直す前提。"""
    data = await request.body()
    if not data or len(data) > 12_000_000:
        raise HTTPException(413, "画像が無い、または大きすぎる")

    def run():
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(422, "画像を読めない")
        return detect_quads(img)
    return {"candidates": await asyncio.to_thread(run)}
