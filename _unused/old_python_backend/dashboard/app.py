"""dashboard：ingest・キュー・worker・DB の状態を一覧で見る Web ページと、その JSON API。

読むだけで、何も書き換えない。ページは数秒ごとに /api/overview を取り直す。
"""

import os
import time
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from common.live import (GROUP, PARTITIONS, estimate_margin, load_cameras, load_estimate, load_live_params, load_floors, now_ms,
                         reset_all, reset_history, stream_name)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://hdt:hdt@postgres:5432/hdt")
STATIC = Path(__file__).parent / "static"
STALE_MS = 15_000  # これより古いハートビート・フレームは「止まっている」とみなす

app = FastAPI(title="dashboard")
r = redis.from_url(REDIS_URL)


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=3)


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _hash(key):
    return {k.decode(): v.decode() for k, v in r.hgetall(key).items()}


def queue_status():
    out = []
    for p in range(PARTITIONS):
        name = stream_name(p)
        item = {"partition": p, "stream": name, "length": 0, "pending": 0, "lag": None}
        try:
            item["length"] = r.xlen(name)
            for g in r.xinfo_groups(name):
                if g["name"].decode() == GROUP:
                    item["pending"] = g["pending"]
                    item["lag"] = g.get("lag")
        except redis.ResponseError:
            pass  # まだ誰も積んでいない
        out.append(item)
    return out


def workers_status():
    out = []
    for key in r.scan_iter("worker:*"):
        h = _hash(key.decode())
        h["name"] = key.decode().split(":", 1)[1]
        h["age_ms"] = now_ms() - _int(h.get("last_seen_ms"))
        h["alive"] = h["age_ms"] < STALE_MS
        out.append(h)
    return sorted(out, key=lambda w: w["name"])


@app.get("/api/overview")
def overview():
    now = now_ms()
    cameras_cfg = load_cameras()
    floors_cfg = load_floors()
    problems = []

    try:
        r.ping()
        redis_ok = True
    except redis.RedisError:
        redis_ok, problems = False, problems + ["Redis に接続できない"]

    ingest_hb = _int(r.get("ingest:heartbeat")) if redis_ok else 0
    queue = queue_status() if redis_ok else []
    workers = workers_status() if redis_ok else []

    cams, floors, crossings, perf, db_ok, since_correction = {}, {}, [], {}, True, {}
    try:
        with db() as conn:
            states = {x["camera_id"]: x for x in conn.execute("SELECT * FROM camera_state").fetchall()}
            floors = {x["floor"]: x for x in conn.execute("SELECT * FROM floor_counts ORDER BY floor").fetchall()}
            crossings = conn.execute(
                "SELECT id, camera_id, floor, ts, direction, track_id, gate FROM crossings ORDER BY id DESC LIMIT 30"
            ).fetchall()
            perf = conn.execute(
                "SELECT count(*) AS frames, avg(infer_ms) AS infer_avg, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY infer_ms) AS infer_p95, "
                "avg(lag_ms) AS lag_avg, percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_ms) AS lag_p95, "
                "avg(n_dets) AS dets_avg FROM frame_log WHERE created_at > now() - interval '60 seconds'"
            ).fetchone()
            since_correction = {x["floor"]: x["n"] for x in conn.execute(
                "SELECT c.floor, count(*) AS n FROM crossings c LEFT JOIN floor_counts f ON f.floor = c.floor "
                "WHERE f.corrected_at IS NULL OR c.ts > f.corrected_at GROUP BY c.floor").fetchall()}
            totals = conn.execute(
                "SELECT (SELECT count(*) FROM crossings) AS crossings, (SELECT count(*) FROM frame_log) AS frames"
            ).fetchone()
    except psycopg.Error as e:
        db_ok, states, totals = False, {}, {}
        problems.append(f"DB に接続できない: {e}")

    for cid, cfg in cameras_cfg.items():
        live = _hash(f"cam:{cid}") if redis_ok else {}
        st = states.get(cid, {})
        last_seen = _int(live.get("last_seen_ms"))
        cams[cid] = {
            "id": cid, "floor": cfg.get("floor"), "sample_fps": cfg["sample_fps"], "tracker": cfg["tracker"],
            "anchor": cfg["anchor"], "line": cfg["line"], "name": cfg.get("name"), "gates": [g["name"] for g in cfg.get("gates") or []],
            "connected": live.get("connected") == "1", "last_seen_age_ms": (now - last_seen) if last_seen else None,
            "decoded": _int(live.get("decoded")), "enqueued": _int(live.get("enqueued")),
            "dropped": _int(live.get("dropped")), "decode_errors": _int(live.get("decode_errors")),
            "partition": _int(live.get("partition"), None) if live.get("partition") else None,
            "in": st.get("in_count", 0), "out": st.get("out_count", 0),
            "last_dets": st.get("last_dets"), "last_tracks": st.get("last_tracks"),
            "last_frame_ts": st.get("last_frame_ts"), "size": [st.get("frame_w"), st.get("frame_h")],
            "has_image": bool(redis_ok and r.exists(f"annotated:{cid}")),
        }

    error_rate = load_estimate()["error_rate"]
    floor_ids = sorted({c["floor"] for c in cams.values() if c["floor"] is not None} | set(floors))
    floor_list = []
    for f in floor_ids:
        row = floors.get(f, {})
        count = row.get("count", 0)
        n_cross = since_correction.get(f, 0)
        # 概算値 = IN − OUT の合算。補正してから今までの通過件数 × error_rate を、± の範囲にする
        margin = estimate_margin(n_cross, error_rate)
        th = floors_cfg.get(f)
        level = None
        if th:
            level = "red" if count >= th["red"] else "yellow" if count >= th["yellow"] else "blue"
        floor_list.append({
            "floor": f, "count": count, "low": max(0, count - margin), "high": count + margin, "margin": margin,
            "crossings_since_correction": n_cross, "corrected_at": row.get("corrected_at"),
            "level": level, "thresholds": th, "updated_at": row.get("updated_at"),
            "cameras": [{"id": c["id"], "name": c.get("name"), "connected": c["connected"], "in": c["in"], "out": c["out"]}
                        for c in cams.values() if c["floor"] == f],
        })

    backlog = sum(q["length"] for q in queue)
    if redis_ok and (now - ingest_hb) > STALE_MS:
        problems.append("ingest が応答していない")
    if redis_ok and not any(w["alive"] for w in workers):
        problems.append("worker が動いていない" + ("（キューが溜まっている）" if backlog else ""))
    for c in cams.values():
        if c["dropped"]:
            problems.append(f"{c['id']}: キューあふれでフレームを {c['dropped']} 枚捨てた（worker が追いついていない）")

    return {
        "now_ms": now,
        "services": {
            "redis": redis_ok, "postgres": db_ok,
            "ingest": redis_ok and (now - ingest_hb) < STALE_MS,
            "workers_alive": sum(1 for w in workers if w["alive"]), "workers_total": len(workers),
        },
        "problems": problems,
        "queue": queue, "backlog": backlog,
        "workers": workers,
        "cameras": list(cams.values()), "live_fps": load_live_params()["live_fps"],
        "floors": floor_list,
        "recent_crossings": crossings,
        "perf_60s": perf, "totals": totals,
    }


@app.get("/api/camera/{camera_id}/frame.jpg")
def camera_frame(camera_id: str):
    data = r.get(f"annotated:{camera_id}")
    if not data:
        raise HTTPException(404, "まだ画像がない")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/crossings")
def crossings(limit: int = Query(100, le=1000), camera_id: str | None = None):
    sql, args = "SELECT id, camera_id, floor, ts, direction, track_id, gate FROM crossings", []
    if camera_id:
        sql, args = sql + " WHERE camera_id = %s", [camera_id]
    with db() as conn:
        return conn.execute(sql + " ORDER BY id DESC LIMIT %s", args + [limit]).fetchall()


@app.get("/healthz")
def healthz():
    return {"ok": True, "time": time.time()}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


class FloorCount(BaseModel):
    count: int = Field(ge=0, le=100000)


@app.post("/api/floors/{floor}/count")
def set_floor_count(floor: int, body: FloorCount):
    """スタッフによる人数の補正。以降の通過件数は、この時刻から数え直す（誤差の範囲も小さくなる）。"""
    with db() as conn:
        conn.execute(
            "INSERT INTO floor_counts (floor, count, updated_at, corrected_at) VALUES (%s, %s, now(), now()) "
            "ON CONFLICT (floor) DO UPDATE SET count = EXCLUDED.count, updated_at = now(), corrected_at = now()",
            (floor, body.count))
    return {"floor": floor, "count": body.count}


@app.post("/api/floors/reset")
def reset_floors():
    """閉場時：全フロアを 0 に戻す。"""
    with db() as conn:
        n = conn.execute("UPDATE floor_counts SET count = 0, updated_at = now(), corrected_at = now()").rowcount
    return {"reset": n}


class HistoryReset(BaseModel):
    camera_id: str | None = None   # 端末ごと
    floor: int | None = None       # フロアごと（camera_id と同時には指定できない）


@app.post("/api/history/reset")
def reset_in_out_history(body: HistoryReset):
    """IN/OUT の履歴（通過イベント）と、端末ごとの累計を消す。何も指定しなければ全部。フロア人数の概算は変えない。"""
    if body.camera_id is not None and body.floor is not None:
        raise HTTPException(422, "camera_id と floor は同時に指定できない")
    with db() as conn:
        n = reset_history(conn, camera_id=body.camera_id, floor=body.floor)
    return {"deleted_crossings": n}


@app.post("/api/reset-all")
def api_reset_all():
    """全部リセット：全端末の IN/OUT の履歴と、全フロアの人数の概算。"""
    with db() as conn:
        return reset_all(conn)


# ---------------------------------------------------------------------------
# ライブ表示：端末を選んでいる間だけ、高い fps で映像を見る
#   開いている間、dashboard が liveview:{id} を立て続ける → ingest が端末に高い fps を頼み、全フレームを
#   livejpeg:{id}（pub/sub）に流す → ここで MJPEG にしてブラウザの <img> に配る。閉じると数秒で元の fps に戻る。
# ---------------------------------------------------------------------------

@app.get("/api/live/{camera_id}/stream")
def live_stream(camera_id: str):
    if camera_id not in load_cameras():
        raise HTTPException(404, "登録されていない端末")
    params = load_live_params()

    def frames():
        ps = r.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(f"livejpeg:{camera_id}")
        t0, last_flag = time.time(), 0.0
        try:
            while time.time() - t0 < params["max_seconds"]:      # 閉じ忘れ対策：上限で止める
                if time.time() - last_flag > 1.0:
                    r.set(f"liveview:{camera_id}", 1, ex=4)      # 見ている合図。途切れると数秒で消える
                    last_flag = time.time()
                m = ps.get_message(timeout=0.5)
                if m and m["type"] == "message":
                    data = m["data"]
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(data)) + data + b"\r\n"
        finally:
            ps.close()

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/live/{camera_id}/info")
def live_info(camera_id: str):
    live = _hash(f"cam:{camera_id}")
    return {
        "streaming": live.get("connected") == "1" or live.get("live_streaming") == "1",   # 映像が届いている（通常の送信、または、ライブ表示のための送信）
        "mode": live.get("mode") if (live.get("connected") == "1" or live.get("live_streaming") == "1") else None,
        "ctl_online": bool(r.exists(f"ctl:{camera_id}")),                  # 送信していなくても、送信ページが開いて待機している
        "rx_fps": float(live["rx_fps"]) if live.get("rx_fps") and (live.get("connected") == "1" or live.get("live_streaming") == "1") else None,   # ingest が受け取っているフレームレート（受信中だけ）
        "live_on": bool(r.exists(f"liveview:{camera_id}")),
        "requested_fps": load_live_params()["live_fps"],
        "max_seconds": load_live_params()["max_seconds"],
    }


@app.get("/api/camera/{camera_id}/result")
def camera_result(camera_id: str):
    """最新の認識結果（検出枠など）。ライブ表示に重ねる。"""
    raw = r.get(f"result:{camera_id}")
    if raw is None:
        return {"boxes": [], "stale": True}
    return Response(content=raw, media_type="application/json", headers={"Cache-Control": "no-store"})
