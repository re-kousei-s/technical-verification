package services

import (
	"bytes"
	"context"
	"encoding/json"
	"image"
	_ "image/jpeg" // image.DecodeConfig で JPEG の縦横を読むために必要
	"log"
	"sync"
	"time"

	"humandetect/config"
	"humandetect/repository"
)

// Conn は、WebSocket 接続のうち、このサービスが使う操作だけを取り出したもの。
// （WebSocket の実装は controller 側に置き、services は通信の細部を知らなくて済むようにする）
type Conn interface {
	ReadMessage() (messageType int, data []byte, err error)
	WriteText(s string) error
	Close() error
}

// 送信のモード
const (
	ModeSend = "send" // 通常の送信。デコードして 5fps に間引き、認識に回す
	ModeLive = "live" // ライブ表示のためだけの送信（スマホは待機していて、頼まれて送る）。認識には回さない
)

// Runtime は、端末ごとの、いまの受信の状況（管理画面・スマホの画面に出す）。
type Runtime struct {
	Active       bool      // 映像を受信している最中か
	Mode         string    // ModeSend / ModeLive
	Decoded      int64     // デコードできたフレーム数
	Enqueued     int64     // キューに積んだフレーム数
	Dropped      int64     // キューがあふれて捨てたフレーム数
	DecodeErrors int64     // デコーダに渡せず捨てたチャンク数
	RxFPS        float64   // 受信しているフレームレート（チャンク/秒）
	LastSeen     time.Time // 最後に受信した時刻
}

// StreamService は、スマホからの映像を受け取り、キューとライブ中継へ流す。
//
//	スマホ ──H.264──▶ [受信]─┬─▶ 全チャンクをそのまま LiveHub へ ─▶ 管理画面（ブラウザがデコード）
//	                         └─▶ ffmpeg でデコード ─▶ 5fps に間引く ─▶ Redis のキュー ─▶ Python worker
//
// 2 つの経路は独立している。ライブ表示中も、キューへの登録（5fps の間引き）は止まらない。
type StreamService struct {
	env     config.Env
	cameras *CameraService
	queue   *repository.QueueRepository
	hub     *LiveHub

	mu      sync.Mutex
	runtime map[string]*Runtime // 端末 ID → 受信の状況
	ctl     map[string]Conn     // 端末 ID → 待機用の接続
	recog   map[string]bool     // 端末 ID → 認識中か（管理画面の指示。DB と同じ内容を、すぐ読めるよう持つ）
}

func NewStreamService(env config.Env, cameras *CameraService, queue *repository.QueueRepository, hub *LiveHub) *StreamService {
	return &StreamService{env: env, cameras: cameras, queue: queue, hub: hub,
		runtime: map[string]*Runtime{}, ctl: map[string]Conn{}, recog: map[string]bool{}}
}

// SetRecognize は、管理画面の「認識を開始／停止」。待機用の接続を通して、スマホに伝わる（2 秒以内）。
func (s *StreamService) SetRecognize(cameraID string, on bool) {
	s.mu.Lock()
	s.recog[cameraID] = on
	s.mu.Unlock()
}

func (s *StreamService) wantRecognize(cameraID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.recog[cameraID]
}

// Snapshot は、端末の受信の状況のコピー。
func (s *StreamService) Snapshot(cameraID string) Runtime {
	s.mu.Lock()
	defer s.mu.Unlock()
	if r, ok := s.runtime[cameraID]; ok {
		return *r
	}
	return Runtime{}
}

// update は、端末の状況を（ロックして）書き換える。
func (s *StreamService) update(cameraID string, f func(r *Runtime)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.runtime[cameraID]
	if !ok {
		r = &Runtime{}
		s.runtime[cameraID] = r
	}
	f(r)
}

// IsStreaming は、いま映像を受信しているか（モードを問わない）。
func (s *StreamService) IsStreaming(cameraID string) bool { return s.Snapshot(cameraID).Active }

// CtlOnline は、スマホの送信ページが待機用の接続を持っているか。
func (s *StreamService) CtlOnline(cameraID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.ctl[cameraID]
	return ok
}

// ---------------------------------------------------------------------------
// 映像の受信（/ws/:id）
// ---------------------------------------------------------------------------

// RunStream は、1 本の映像の接続を最後まで処理する。接続が切れるまで戻らない。
// stripTsHeader が true なら、各チャンクの先頭 8 バイト（撮影時刻）を取り除く。
func (s *StreamService) RunStream(cameraID, mode string, stripTsHeader bool, conn Conn) error {
	cam, err := s.cameras.Get(cameraID)
	if err != nil {
		return err
	}
	if cam == nil {
		return errNotFound("登録されていない端末")
	}
	y, err := s.cameras.Yaml()
	if err != nil {
		return err
	}

	// 同じ端末の映像は 1 本だけ受け付ける（追跡の状態が混ざらないように）
	busy := false
	s.update(cameraID, func(r *Runtime) {
		if r.Active {
			busy = true
			return
		}
		*r = Runtime{Active: true, Mode: mode, LastSeen: time.Now()}
	})
	if busy {
		return errConflict("camera already streaming")
	}
	log.Printf("映像の受信を開始 %s (mode=%s, sample_fps=%v)", cameraID, mode, cam.SampleFPS)

	stop := make(chan struct{}) // この関数が終わるとき閉じる。裏で動く処理を止める合図
	var wg sync.WaitGroup
	defer func() {
		close(stop)
		wg.Wait()
		s.hub.Reset(cameraID)
		s.update(cameraID, func(r *Runtime) { r.Active = false; r.RxFPS = 0 })
		log.Printf("映像の受信を終了 %s", cameraID)
	}()

	// 認識に回す場合だけ、ffmpeg でデコードする（ライブ表示のためだけの送信は、中継するだけでよい）
	var dec *Decoder
	if mode == ModeSend {
		if dec, err = s.startDecoder(cameraID, cam.SampleFPS, stop, &wg); err != nil {
			return err
		}
		defer func() { dec.Close() }()

		// ライブ表示を見ている人がいる間だけ、端末に高い fps で送るよう頼む
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.controlSendFPS(cameraID, y, conn, stop)
		}()
	} else {
		// プレビュー専用の送信でも、新しく見始めた人がいたら、IDR を送り直させる
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.controlIDR(cameraID, conn, stop)
		}()
	}

	// 受信ループ：届いたチャンクを、ライブ中継とデコーダの両方へ渡す
	window, windowStart := 0, time.Now()
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return nil // 切断は、エラーではなく正常な終了として扱う
		}
		if stripTsHeader && len(data) >= 8 {
			data = data[8:]
		}
		if len(data) == 0 {
			continue
		}

		s.hub.Publish(cameraID, data) // ① 全チャンクを、そのまま（デコードせず）管理画面へ

		if dec != nil { // ② 認識用：ffmpeg に渡す。ffmpeg が止まっていたら起動し直す
			select {
			case <-dec.Done():
				dec.Close()
				if dec, err = s.startDecoder(cameraID, cam.SampleFPS, stop, &wg); err != nil {
					log.Printf("ffmpeg を起動し直せない %s: %v", cameraID, err)
					return err
				}
			default:
			}
			if !dec.Write(data) {
				s.update(cameraID, func(r *Runtime) { r.DecodeErrors++ }) // デコーダが追いつかず、捨てた
			}
		}

		// 受信フレームレートの実測（1 秒ごと）
		window++
		if elapsed := time.Since(windowStart); elapsed >= time.Second {
			fps := float64(window) / elapsed.Seconds()
			s.update(cameraID, func(r *Runtime) { r.RxFPS = fps })
			window, windowStart = 0, time.Now()
		}
		s.update(cameraID, func(r *Runtime) { r.LastSeen = time.Now() })
	}
}

// startDecoder は、ffmpeg を起動し、出てきた JPEG を 5fps に間引いてキューに積む処理を裏で始める。
func (s *StreamService) startDecoder(cameraID string, sampleFPS float64, stop <-chan struct{}, wg *sync.WaitGroup) (*Decoder, error) {
	dec, err := NewDecoder()
	if err != nil {
		return nil, err
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		s.sampleLoop(cameraID, sampleFPS, dec, stop)
	}()
	return dec, nil
}

// sampleLoop は、デコードされた JPEG を、認識に回す頻度（sample_fps）に間引いて、キューに積む。
//
// 間引くのは「デコードしたあと」。H.264 は途中のフレームを捨てるとデコードできないので、
// 全フレームをデコードしてから間引く。この処理は、ライブ表示の有無に関係なく動き続ける。
func (s *StreamService) sampleLoop(cameraID string, sampleFPS float64, dec *Decoder, stop <-chan struct{}) {
	interval := time.Duration(float64(time.Second) / sampleFPS)
	const tolerance = 20 * time.Millisecond // 少し早く届いても採る（30fps なら 1 フレーム以内）
	var last time.Time
	partition := s.queue.PartitionOf(cameraID)

	for {
		select {
		case <-stop:
			return
		case jpeg, ok := <-dec.Frames():
			if !ok {
				return // ffmpeg が終わった
			}
			now := time.Now()
			s.update(cameraID, func(r *Runtime) { r.Decoded++ })
			if !last.IsZero() && now.Sub(last) < interval-tolerance {
				continue // 間引く
			}
			last = now

			// キューがあふれそうなら、新しいフレームを捨てる（worker が追いついていない目印）
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			if n, err := s.queue.Length(ctx, partition); err == nil && n >= int64(s.env.MaxQueue) {
				s.update(cameraID, func(r *Runtime) { r.Dropped++ })
				cancel()
				continue
			}
			w, h := jpegSize(jpeg)
			if err := s.queue.Enqueue(ctx, cameraID, now.UnixMilli(), w, h, jpeg); err != nil {
				log.Printf("キューに積めない %s: %v", cameraID, err)
			} else {
				s.update(cameraID, func(r *Runtime) { r.Enqueued++ })
			}
			cancel()
		}
	}
}

// jpegSize は、JPEG の縦横を読む（画像全体はデコードしない）。
func jpegSize(jpeg []byte) (w, h int) {
	cfg, _, err := image.DecodeConfig(bytes.NewReader(jpeg))
	if err != nil {
		return 0, 0
	}
	return cfg.Width, cfg.Height
}

// controlSendFPS は、通常の送信中の端末に「何 fps で送るか」を指示し続ける。
// ライブ表示を見ている人がいれば高い fps（live_fps）、いなければ元の fps（normal_fps）。
func (s *StreamService) controlSendFPS(cameraID string, y *config.Yaml, conn Conn, stop <-chan struct{}) {
	var sent float64
	joins := s.hub.Joins(cameraID)
	tick := time.NewTicker(200 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-stop:
			return
		case <-tick.C:
			want, live := y.Live.NormalFPS, false
			if s.hub.Viewers(cameraID) > 0 {
				want, live = y.Live.LiveFPS, true
			}
			// 誰かが新しく見始めたら、fps が同じでも、端末に IDR（キーフレーム）を送り直させる。
			// 見始めた人は、キーフレームからでないとデコードできないため（GOP を覚えていても、できるだけ新しい IDR から始めたい）
			idr := false
			if j := s.hub.Joins(cameraID); j != joins {
				joins, idr = j, true
			}
			if want != sent || idr {
				msg, _ := json.Marshal(map[string]any{"send_fps": want, "live": live, "idr": idr})
				if err := conn.WriteText(string(msg)); err != nil {
					return // 接続が閉じた
				}
				log.Printf("端末に指示 %s: %v fps (live=%v, idr=%v)", cameraID, want, live, idr)
				sent = want
			}
		}
	}
}

// controlIDR は、新しく見始めた人がいるたびに、端末に IDR（キーフレーム）を送らせる（fps の指示はしない）。
func (s *StreamService) controlIDR(cameraID string, conn Conn, stop <-chan struct{}) {
	joins := s.hub.Joins(cameraID)
	tick := time.NewTicker(200 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-stop:
			return
		case <-tick.C:
			if j := s.hub.Joins(cameraID); j != joins {
				joins = j
				if conn.WriteText(`{"idr":true}`) != nil {
					return
				}
				log.Printf("端末に IDR を指示 %s", cameraID)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// 待機用の接続（/ctl/:id）
// ---------------------------------------------------------------------------

// RunControl は、スマホの送信ページが開いている間ずっとつなぐ、待機用の接続を処理する。映像は流れない。
//
// ダッシュボードでライブ表示が開かれたとき、端末がまだ送信していなければ、ここから「配信を始めて」と頼む。
// 端末は ModeLive の映像（プレビュー専用）を送ってくる。見終わったら「止めて」と頼む。
func (s *StreamService) RunControl(cameraID string, conn Conn) error {
	cam, err := s.cameras.Get(cameraID)
	if err != nil {
		return err
	}
	if cam == nil {
		return errNotFound("登録されていない端末")
	}
	y, err := s.cameras.Yaml()
	if err != nil {
		return err
	}

	// 同じ端末の新しいページが開いたら、古い方を閉じる
	s.mu.Lock()
	old := s.ctl[cameraID]
	s.ctl[cameraID] = conn
	s.mu.Unlock()
	if old != nil {
		_ = old.Close()
	}
	s.SetRecognize(cameraID, cam.Recognizing) // DB の状態を、最初に読み込む（再起動のあとも、続きから再開できる）
	log.Printf("待機用の接続 %s（認識中=%v）", cameraID, cam.Recognizing)

	closed := make(chan struct{})
	go func() { // 読むのは、切断を知るためだけ
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				close(closed)
				return
			}
		}
	}()
	defer func() {
		s.mu.Lock()
		if s.ctl[cameraID] == conn {
			delete(s.ctl, cameraID)
		}
		s.mu.Unlock()
		log.Printf("待機用の接続が切れた %s", cameraID)
	}()

	var askedAt time.Time    // 「配信を始めて」と頼んだ時刻（頼んでいなければゼロ値）
	var recAskedAt time.Time // 「認識を始めて／止めて」と頼んだ時刻
	tick := time.NewTicker(500 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-closed:
			return nil
		case <-tick.C:
			viewers := s.hub.Viewers(cameraID)
			rt := s.Snapshot(cameraID)
			rec := s.wantRecognize(cameraID)
			sending := rt.Active && rt.Mode == ModeSend // 認識用の映像を送っているか
			// 認識の開始・停止：管理画面の指示と、スマホの様子が違うときだけ頼む（6 秒たっても変わらなければ、もう一度）
			if rec != sending && (recAskedAt.IsZero() || time.Since(recAskedAt) > 6*time.Second) {
				cmd := "recognize_stop"
				if rec {
					cmd = "recognize_start"
				}
				if conn.WriteText(`{"cmd":"`+cmd+`"}`) != nil {
					return nil
				}
				recAskedAt = time.Now()
				log.Printf("端末に指示 %s: %s", cameraID, cmd)
			} else if rec == sending {
				recAskedAt = time.Time{}
			}
			switch {
			case viewers > 0 && !rt.Active && !rec && (askedAt.IsZero() || time.Since(askedAt) > 6*time.Second):
				// 見ている人がいるのに、端末が送っていない → 配信を頼む（6 秒たっても始まらなければ、もう一度）
				msg, _ := json.Marshal(map[string]any{"cmd": "live_start", "fps": y.Live.LiveFPS})
				if conn.WriteText(string(msg)) != nil {
					return nil
				}
				askedAt = time.Now()
			case viewers == 0 && !askedAt.IsZero():
				// 誰も見なくなった → 配信を止めてもらう
				if conn.WriteText(`{"cmd":"live_stop"}`) != nil {
					return nil
				}
				askedAt = time.Time{}
			case !askedAt.IsZero() && rt.Active && rt.Mode == ModeSend:
				askedAt = time.Time{} // 見ている間に、端末が通常の送信を始めた。止めてもらう必要はない
			}
		}
	}
}

// ---------------------------------------------------------------------------
// ライブ表示（管理画面）
// ---------------------------------------------------------------------------

// LiveInfo は、ライブ表示の画面に出す状況。
type LiveInfo struct {
	Streaming    bool     `json:"streaming"`     // 映像が届いている（通常の送信、またはライブのための送信）
	Mode         *string  `json:"mode"`          // 届いている映像のモード
	CtlOnline    bool     `json:"ctl_online"`    // 送信していなくても、送信ページが開いて待機している
	RxFPS        *float64 `json:"rx_fps"`        // 受信しているフレームレート
	LiveOn       bool     `json:"live_on"`       // 誰かがライブ表示を見ている
	RequestedFPS float64  `json:"requested_fps"` // 端末に頼む fps
	MaxSeconds   int      `json:"max_seconds"`
}

func (s *StreamService) LiveInfo(cameraID string) (LiveInfo, error) {
	y, err := s.cameras.Yaml()
	if err != nil {
		return LiveInfo{}, err
	}
	rt := s.Snapshot(cameraID)
	info := LiveInfo{
		Streaming: rt.Active, CtlOnline: s.CtlOnline(cameraID), LiveOn: s.hub.Viewers(cameraID) > 0,
		RequestedFPS: y.Live.LiveFPS, MaxSeconds: y.Live.MaxSecond,
	}
	if rt.Active {
		info.Mode, info.RxFPS = &rt.Mode, &rt.RxFPS
	}
	return info, nil
}

// Subscribe は、ライブ表示（H.264 の中継）を見始める。
func (s *StreamService) Subscribe(cameraID string) (*Viewer, error) {
	cam, err := s.cameras.Get(cameraID)
	if err != nil {
		return nil, err
	}
	if cam == nil {
		return nil, errNotFound("登録されていない端末")
	}
	return s.hub.Subscribe(cameraID), nil
}

// Unsubscribe は、ライブ表示をやめる。
func (s *StreamService) Unsubscribe(cameraID string, v *Viewer) { s.hub.Unsubscribe(cameraID, v) }

// MaxLiveSeconds は、1 回のライブ表示の上限（閉じ忘れ対策）。
func (s *StreamService) MaxLiveSeconds() time.Duration {
	if y, err := s.cameras.Yaml(); err == nil {
		return time.Duration(y.Live.MaxSecond) * time.Second
	}
	return 10 * time.Minute
}
