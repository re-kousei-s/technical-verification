package services

import (
	"encoding/binary"
	"sync"
	"time"
)

// Chunk は、端末から届いた H.264 の 1 フレームぶん（Annex B）と、そのフレームを撮った時刻。
//
// 送信ページは、各フレームの先頭に「HDF1」＋撮った時刻（ミリ秒、8 バイト）を付けて送る。撮った時刻は、そのフレームの ID でもある。
// 同じ絵を送り直すとき（見始めた人のためのキーフレーム）は、同じ時刻が付く。認識は、一度処理した時刻のフレームを、二度処理しない。
// CapMs は、サーバーの時計に直した撮影時刻（0＝付いていない古い送信ページ）。
// JPEG が true なら、Data は JPEG 1 枚（送り方 jpeg。先頭は「HDJ1」）。どのフレームも、それだけで絵になる。
type Chunk struct {
	Data  []byte
	CapMs int64
	JPEG  bool
}

// FrameHandler は、端末から届いたチャンクを受け取る関数。購読者（認識に回す処理、管理画面のライブ表示）が、それぞれ登録する。
type FrameHandler func(c Chunk)

// splitHeader は、先頭の「HDF1（H.264）／ HDJ1（JPEG） ＋ 撮った時刻」を外す。付いていなければ、そのまま（H.264・時刻 0）。
func splitHeader(b []byte) (data []byte, capMs int64, jpeg bool) {
	if len(b) > 12 && b[0] == 'H' && b[1] == 'D' && (b[2] == 'F' || b[2] == 'J') && b[3] == '1' {
		return b[12:], int64(binary.BigEndian.Uint64(b[4:12])), b[2] == 'J'
	}
	return b, 0, false
}

const maxGopBytes = 16 << 20 // GOP として覚えておく上限（超えたら諦めて、次のキーフレームを待つ）

// Device は、端末（スマホ）1 台ぶんのハブ。
//
//	スマホ ─ws─▶ Publish ─┬─▶ 認識（デコード → 間引き → Redis）   ← 認識中だけ登録される
//	                       └─▶ ライブ表示（H.264 をそのまま WS へ）  ← 見ている人がいる間だけ登録される
//
// 購読者は、コールバックで登録する。登録が 1 つも無ければ、届いたチャンクは捨てる。
type Device struct {
	ID string

	mu        sync.Mutex
	phone     Conn   // スマホの接続（無ければ nil）
	recognize bool   // 認識中か（管理画面の指示）
	settings  []byte // スマホのカメラの設定（管理画面の指示）。スマホに伝える
	lines     []byte // 数える線（JSON）。管理画面で編集されたら、スマホにも伝える
	caps      []byte // スマホが報告した、カメラの能力（カメラの一覧・ズームの範囲・いまの設定）
	subs      map[int]FrameHandler
	nextSub   int
	viewers   int     // リアルタイム表示（高い fps）を見ている人の数
	thumbs    int     // 一覧の小さな表示（低い fps）を見ている人の数
	joins     int     // 見始めた人の累計（増えたら、スマホに IDR を送り直させる）
	gop       []Chunk // 最後のキーフレームから今までのチャンク（途中から見ても映るように）
	gopBytes  int
	rt        Runtime
	window    int // 受信フレームレートの実測用
	windowAt  time.Time
	rxWin     int       // 受信量の実測用（この 1 秒の間に届いたバイト数）
	txWin     int       // 管理画面へ送った量の実測用
	txAt      time.Time // 送った量の、いまの区切りの始まり
	clock     phoneClock
	lastCap   int64 // 認識が、最後に見たフレームの撮影時刻（サーバーの時計）。これ以前のフレームは、二度処理しない
}

// phoneClock は、スマホの時計とサーバーの時計のずれ（届いた時刻 − 撮った時刻 の、直近 30 秒の最小値）。
// 最小値を使うのは、いちばん遅れずに届いたフレームの差が、時計のずれにいちばん近いから（送信が遅れたフレームの時刻を、ずらさない）。
type phoneClock struct {
	samples []struct{ at, delta int64 }
}

func (c *phoneClock) toServer(capMs, nowMs int64) int64 {
	c.samples = append(c.samples, struct{ at, delta int64 }{nowMs, nowMs - capMs})
	k := 0
	for k < len(c.samples) && nowMs-c.samples[k].at > 30_000 {
		k++
	}
	c.samples = c.samples[k:]
	m := c.samples[0].delta
	for _, s := range c.samples[1:] {
		if s.delta < m {
			m = s.delta
		}
	}
	return capMs + m
}

// claimFrame は、認識に回すフレームを、1 度だけにする。撮影時刻が、前に見たフレーム以前なら false（処理済み）。
// スマホの時計が大きく戻った（1 分以上）ときは、新しい送信とみなして、受け入れ直す。
func (d *Device) claimFrame(capMs int64) bool {
	if capMs == 0 {
		return true // 時刻の付いていない古い送信ページ：見分けられない
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if capMs <= d.lastCap && d.lastCap-capMs < 60_000 {
		return false
	}
	d.lastCap = capMs
	return true
}

func newDevice(id string) *Device {
	return &Device{ID: id, subs: map[int]FrameHandler{}, windowAt: time.Now()}
}

// Subscribe は、チャンクの購読を始める。戻り値の関数を呼ぶと、やめる。
// replayGOP が true なら、最初に、覚えている GOP を渡す（ライブ表示の途中参加用）。
func (d *Device) Subscribe(h FrameHandler, replayGOP bool) (cancel func()) {
	d.mu.Lock()
	id := d.nextSub
	d.nextSub++
	var gop []Chunk
	if replayGOP {
		gop = append(gop, d.gop...)
	}
	d.subs[id] = h
	d.mu.Unlock()
	for _, c := range gop {
		h(c)
	}
	return func() {
		d.mu.Lock()
		delete(d.subs, id)
		d.mu.Unlock()
	}
}

// Publish は、届いたメッセージを、全購読者に渡す（受信ループから、1 フレームごとに呼ばれる）。
func (d *Device) Publish(msg []byte) {
	data, cap, jpeg := splitHeader(msg)
	key := jpeg || hasKeyframe(data) // JPEG は、どの 1 枚も、それだけで絵になる（覚えておくのは、最後の 1 枚だけ）
	d.mu.Lock()
	chunk := Chunk{Data: data, JPEG: jpeg}
	if cap > 0 {
		chunk.CapMs = d.clock.toServer(cap, time.Now().UnixMilli())
	}
	if key {
		d.gop, d.gopBytes = d.gop[:0], 0
	}
	if d.gopBytes+len(data) <= maxGopBytes {
		d.gop = append(d.gop, chunk)
		d.gopBytes += len(data)
	} else {
		d.gop, d.gopBytes = nil, 0 // 大きすぎる。次のキーフレームまで覚えない
	}
	// 受信の実測
	d.rt.Decoded++ // 受信したフレーム数（認識中は、デコードに渡す数でもある）
	d.rt.LastSeen = time.Now()
	d.window++
	d.rt.RxBytes += int64(len(msg))
	d.rxWin += len(msg)
	if el := time.Since(d.windowAt); el >= time.Second {
		d.rt.RxFPS = float64(d.window) / el.Seconds()
		d.rt.RxKbps = float64(d.rxWin) * 8 / 1000 / el.Seconds()
		d.window, d.rxWin, d.windowAt = 0, 0, time.Now()
	}
	handlers := make([]FrameHandler, 0, len(d.subs))
	for _, h := range d.subs {
		handlers = append(handlers, h)
	}
	d.mu.Unlock()
	for _, h := range handlers { // ロックの外で呼ぶ（購読者の処理が遅くても、他を止めない）
		h(chunk)
	}
}

// Viewer は、ライブ表示の視聴者 1 人。C から H.264 のチャンクを受け取る。
type Viewer struct {
	C       chan []byte
	needKey bool // 詰まってチャンクを捨てたら、次のキーフレームまで渡さない（壊れた絵を見せないため）
}

const viewerBuffer = 600 // 視聴者ごとの待ち行列の長さ（30fps の 10 秒分 + 余裕）

// AddViewer は、映像の視聴を始める。戻り値の cancel で、やめる。
// thumb が true なら、一覧の小さな表示（低い fps で足りる）。false なら、リアルタイム表示（高い fps を頼む）。
func (d *Device) AddViewer(thumb bool) (*Viewer, func()) {
	v := &Viewer{C: make(chan []byte, viewerBuffer)}
	var mu sync.Mutex
	cancelSub := d.Subscribe(func(c Chunk) {
		chunk := c.Data
		mu.Lock()
		defer mu.Unlock()
		key := c.JPEG || hasKeyframe(chunk)
		if v.needKey && !key {
			return // 捨てたあとは、キーフレームが来るまで待つ
		}
		select {
		case v.C <- chunk:
			if key {
				v.needKey = false
			}
		default:
			v.needKey = true // 詰まった。捨てて、次のキーフレームから再開する
		}
	}, true)
	d.mu.Lock()
	if thumb {
		d.thumbs++
	} else {
		d.viewers++
	}
	d.joins++
	d.mu.Unlock()
	return v, func() {
		cancelSub()
		d.mu.Lock()
		if thumb {
			d.thumbs--
		} else {
			d.viewers--
		}
		d.mu.Unlock()
	}
}

// reset は、スマホが切れたとき、古い GOP と受信の状況を捨てる（次に繋がったとき、古い絵を見せないため）。
func (d *Device) reset() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.gop, d.gopBytes = nil, 0
	d.rt.Active, d.rt.RxFPS, d.rt.RxKbps = false, 0, 0
}

// addTx は、管理画面へ送った量を足す（1 秒ごとに、速さを出し直す）。
func (d *Device) addTx(n int) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.rt.TxBytes += int64(n)
	d.txWin += n
	if el := time.Since(d.txAt); el >= time.Second {
		d.rt.TxKbps = float64(d.txWin) * 8 / 1000 / el.Seconds()
		d.txWin, d.txAt = 0, time.Now()
	}
}

// update は、受信の状況を（ロックして）書き換える。
func (d *Device) update(f func(rt *Runtime)) {
	d.mu.Lock()
	defer d.mu.Unlock()
	f(&d.rt)
}
