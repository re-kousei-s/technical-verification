"""フレームを、端末ごとに 1 度だけ処理するための見張り。

フレームの時刻（ts_ms）は、スマホで撮った時刻（サーバーの時計に直したもの）で、フレームの ID でもある。
同じ端末のフレームは、同じ分割を、撮った順に流れてくるので、前に処理した時刻以前のフレームは、処理済み（送り直し・再配達）とみなして捨てる。
  - キューの再配達：worker を再起動すると、ACK していない分を、もう一度読む
  - 送信ページ・backend の送り直し：同じ絵（同じ撮影時刻）が、もう一度届く
スマホの時計が大きく戻った（60 秒以上）ときは、新しい送信とみなして、受け入れ直す。
"""

RESET_MS = 60_000


class Once:
    def __init__(self, load=None):
        self.last = {}  # 端末ID → 最後に処理したフレームの時刻
        self.load = load  # 初めて見る端末の、前回までの最後の時刻を読む関数（なければ None）
        self.dropped = 0

    def first(self, camera_id, ts_ms):
        """このフレームを、初めて処理するなら True（そのとき、処理済みとして覚える）。"""
        if camera_id not in self.last and self.load is not None:
            self.last[camera_id] = self.load(camera_id) or 0
        last = self.last.get(camera_id, 0)
        if ts_ms <= last and last - ts_ms < RESET_MS:
            self.dropped += 1
            return False
        self.last[camera_id] = ts_ms
        return True
