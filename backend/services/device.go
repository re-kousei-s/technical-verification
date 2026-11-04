package services

import (
	"sync"
	"time"
)

// FrameHandler は、端末から届いた H.264 のチャンク（1 フレームぶん）を受け取る関数。
// 購読者（認識に回す処理、管理画面のライブ表示）が、それぞれ登録する。
type FrameHandler func(chunk []byte)

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
	viewers   int      // リアルタイム表示（高い fps）を見ている人の数
	thumbs    int      // 一覧の小さな表示（低い fps）を見ている人の数
	joins     int      // 見始めた人の累計（増えたら、スマホに IDR を送り直させる）
	gop       [][]byte // 最後のキーフレームから今までのチャンク（途中から見ても映るように）
	gopBytes  int
	rt        Runtime
	window    int // 受信フレームレートの実測用
	windowAt  time.Time
	rxWin     int       // 受信量の実測用（この 1 秒の間に届いたバイト数）
	txWin     int       // 管理画面へ送った量の実測用
	txAt      time.Time // 送った量の、いまの区切りの始まり
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
	var gop [][]byte
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

// Publish は、届いたチャンクを、全購読者に渡す（受信ループから、1 チャンクごとに呼ばれる）。
func (d *Device) Publish(chunk []byte) {
	key := hasKeyframe(chunk)
	d.mu.Lock()
	if key {
		d.gop, d.gopBytes = d.gop[:0], 0
	}
	if d.gopBytes+len(chunk) <= maxGopBytes {
		d.gop = append(d.gop, chunk)
		d.gopBytes += len(chunk)
	} else {
		d.gop, d.gopBytes = nil, 0 // 大きすぎる。次のキーフレームまで覚えない
	}
	// 受信の実測
	d.rt.Decoded++ // 受信したフレーム数（認識中は、デコードに渡す数でもある）
	d.rt.LastSeen = time.Now()
	d.window++
	d.rt.RxBytes += int64(len(chunk))
	d.rxWin += len(chunk)
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
	cancelSub := d.Subscribe(func(chunk []byte) {
		mu.Lock()
		defer mu.Unlock()
		key := hasKeyframe(chunk)
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
