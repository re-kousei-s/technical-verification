"""ゲート（ドアの領域）での出入りを数える。

入口・エレベーター・階段のドアは、人がその中に入ると見えなくなる。線を越えるのではなく、
  ・ドアの領域の中で追跡が始まった   → 「出てきた」= フロアに入った（IN）
  ・ドアの領域の中で追跡が途切れた   → 「入って消えた」= フロアから出た（OUT）
と数える。領域は、ドアの四角に、下端の外側へ floor_margin だけ足したもの（ドアの前に立つ人の足元を含めるため）。
人の位置は、枠の足元（bottom_center）で判定する。

注意（限界）
  ・ドアの領域の中で検出が途切れると「消えた」になり、そのあと検出が戻ると「現れた」になる（足し引きで0になる）。
  ・ドアの前を横切る人は、足元が領域に入る位置を通ると、現れる・消える扱いになりうる（領域の外側なら数えない）。
"""

import cv2
import numpy as np
import supervision as sv


def zone_polygon(quad, w, h, floor_margin=0.25):
    """ドアの四角 [左上, 右上, 右下, 左下]（割合）から、判定する領域（px の多角形）を作る。下端を floor_margin だけ延ばす。"""
    q = np.array(quad, dtype=np.float32) * [w, h]
    tl, tr, br, bl = q
    return np.array([tl, tr, br + (br - tr) * floor_margin, bl + (bl - tl) * floor_margin], dtype=np.float32)


class GateMonitor:
    def __init__(self, gates, w, h, vanish_seconds=1.0, warmup_seconds=1.5, floor_margin=0.25, min_hits=3):
        self.gates = [{"id": g["id"], "name": g["name"], "kind": g.get("kind", "door"),
                       "poly": zone_polygon(g["quad"], w, h, floor_margin)} for g in gates]
        self.vanish_seconds, self.warmup_seconds, self.min_hits = vanish_seconds, warmup_seconds, min_hits
        self.tracks = {}      # 追跡ID -> {first_t, last_t, hits, born_gate, last_gate, last_xy, appeared}
        self.t0 = None
        self.last_t = None

    def _gate_at(self, x, y):
        for g in self.gates:
            if cv2.pointPolygonTest(g["poly"], (float(x), float(y)), False) >= 0:
                return g
        return None

    def update(self, tracked, t):
        """1フレームぶんを渡す。戻り値は、このフレームで起きた出入り [(t, "in"/"out", 追跡ID, x, y, ゲート名)]。"""
        events = []
        if self.t0 is None:
            self.t0 = t
        if self.last_t is not None and t - self.last_t > max(3.0, 3 * self.vanish_seconds):
            self.tracks.clear()           # 長く途切れた（再接続など）。止まっていた間の「消えた」は数えない
            self.t0 = t
        self.last_t = t

        present = set()
        if len(tracked):
            pts = tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)
            for (x, y), tid in zip(pts, tracked.tracker_id):
                tid = int(tid)
                if tid < 0:
                    continue          # まだ確定していない追跡
                present.add(tid)
                g = self._gate_at(x, y)
                tr = self.tracks.get(tid)
                if tr is None:
                    tr = self.tracks[tid] = {"first_t": t, "last_t": t, "hits": 1, "born_gate": g, "last_gate": g,
                                             "last_xy": (x, y), "appeared": False}
                else:
                    tr.update(last_t=t, hits=tr["hits"] + 1, last_gate=g, last_xy=(x, y))
                # ドアの領域の中で生まれ、ある程度続いた追跡 = ドアから出てきた人
                if (tr["born_gate"] is not None and not tr["appeared"] and tr["hits"] >= 2
                        and tr["first_t"] - self.t0 >= self.warmup_seconds):
                    tr["appeared"] = True
                    events.append((t, "in", tid, float(tr["last_xy"][0]), float(tr["last_xy"][1]), tr["born_gate"]["name"]))

        # 見えなくなって vanish_seconds たった追跡のうち、最後の位置がドアの領域の中だったもの = ドアに入った人
        for tid in [k for k in self.tracks if k not in present]:
            tr = self.tracks[tid]
            if t - tr["last_t"] >= self.vanish_seconds:
                if tr["last_gate"] is not None and tr["hits"] >= self.min_hits:
                    events.append((tr["last_t"], "out", tid, float(tr["last_xy"][0]), float(tr["last_xy"][1]), tr["last_gate"]["name"]))
                del self.tracks[tid]
        return events
