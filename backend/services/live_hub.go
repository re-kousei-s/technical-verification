package services

import "sync"

// LiveHub は、スマホから届いた H.264 を、そのまま管理画面（視聴者）へ配る中継所。
//
//   - デコードはしない。届いたチャンクをコピーせずに渡すだけ（デコードは管理画面のブラウザが行う）。
//   - 認識用の「デコードして 5fps に間引く」処理とは別の経路なので、ライブ表示中も認識は止まらない。
//   - H.264 は、途中から見始めても、キーフレームからでないとデコードできない。そこで、
//     「最後のキーフレームから今まで」のチャンク（GOP）を覚えておき、新しい視聴者に最初に渡す。
type LiveHub struct {
	mu    sync.Mutex
	rooms map[string]*room // 端末 ID → その端末の視聴の場
}

// room は、1 台の端末ぶんの視聴の場。
type room struct {
	viewers  map[*Viewer]struct{}
	joins    int      // 視聴を始めた人の累計（新しく見始めた人がいるかを、端末への指示に使う）
	gop      [][]byte // 最後のキーフレームから今までのチャンク
	gopBytes int
}

// Viewer は、視聴者 1 人。C から H.264 のチャンクを受け取る。
type Viewer struct {
	C       chan []byte
	needKey bool // 詰まってチャンクを捨てたら、次のキーフレームまで渡さない（壊れた絵を見せないため）
}

const (
	viewerBuffer = 600      // 視聴者ごとの待ち行列の長さ（30fps の 10 秒分 + 余裕）
	maxGopBytes  = 16 << 20 // GOP として覚えておく上限（超えたら諦めて、次のキーフレームを待つ）
)

func NewLiveHub() *LiveHub { return &LiveHub{rooms: map[string]*room{}} }

func (h *LiveHub) room(cameraID string) *room {
	r, ok := h.rooms[cameraID]
	if !ok {
		r = &room{viewers: map[*Viewer]struct{}{}}
		h.rooms[cameraID] = r
	}
	return r
}

// Publish は、端末から届いたチャンクを、全視聴者に渡す。受信ループから、1 チャンクごとに呼ばれる。
func (h *LiveHub) Publish(cameraID string, chunk []byte) {
	key := hasKeyframe(chunk)

	h.mu.Lock()
	defer h.mu.Unlock()
	r := h.room(cameraID)

	// GOP を更新する：キーフレームが来たら作り直し、それ以外は足していく
	if key {
		r.gop, r.gopBytes = r.gop[:0], 0
	}
	if r.gopBytes+len(chunk) <= maxGopBytes {
		r.gop = append(r.gop, chunk)
		r.gopBytes += len(chunk)
	} else {
		r.gop, r.gopBytes = nil, 0 // 大きすぎる。次のキーフレームまで覚えない
	}

	for v := range r.viewers {
		if v.needKey && !key {
			continue // 捨てたあとは、キーフレームが来るまで待つ
		}
		select {
		case v.C <- chunk:
			if key {
				v.needKey = false
			}
		default:
			v.needKey = true // 詰まった。捨てて、次のキーフレームから再開する
		}
	}
}

// Subscribe は、視聴を始める。最初に、覚えている GOP（最後のキーフレームから今まで）が渡される。
func (h *LiveHub) Subscribe(cameraID string) *Viewer {
	v := &Viewer{C: make(chan []byte, viewerBuffer)}
	h.mu.Lock()
	defer h.mu.Unlock()
	r := h.room(cameraID)
	for _, chunk := range r.gop {
		v.C <- chunk
	}
	r.viewers[v] = struct{}{}
	r.joins++
	return v
}

// Unsubscribe は、視聴をやめる。
func (h *LiveHub) Unsubscribe(cameraID string, v *Viewer) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.room(cameraID).viewers, v)
}

// Joins は、視聴を始めた人の累計。前回から増えていれば、誰かが新しく見始めたということ。
func (h *LiveHub) Joins(cameraID string) int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.room(cameraID).joins
}

// Viewers は、いま見ている人の数。1 人以上いる間だけ、端末に高い fps を頼む。
func (h *LiveHub) Viewers(cameraID string) int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.room(cameraID).viewers)
}

// Reset は、端末が送信をやめたとき、古い GOP を捨てる（次に繋がったとき、古い絵を見せないため）。
func (h *LiveHub) Reset(cameraID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	r := h.room(cameraID)
	r.gop, r.gopBytes = nil, 0
}
