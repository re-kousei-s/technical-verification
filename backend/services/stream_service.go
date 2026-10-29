package services

import (
	"encoding/json"
	"log"
	"strings"
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

const binaryMessage = 2 // WebSocket のバイナリメッセージの種類（映像のチャンク）

// Runtime は、端末ごとの、いまの受信の状況（管理画面・スマホの画面に出す）。
type Runtime struct {
	Active       bool      // 映像を受信している最中か（直近 3 秒以内に届いている）
	Decoded      int64     // 受信したフレーム数
	Enqueued     int64     // キューに積んだフレーム数
	Dropped      int64     // キューがあふれて捨てたフレーム数
	DecodeErrors int64     // デコーダに渡せず捨てたチャンク数
	RxFPS        float64   // 受信しているフレームレート（チャンク/秒）
	LastSeen     time.Time // 最後に受信した時刻
}

// StreamService は、端末（スマホ）の接続と、端末ごとのハブ（Device）を管理する。
//
//	スマホ ─ws 1 本─▶ Device.Publish ─┬─▶ Recognizer（認識中だけ）──▶ Redis ──▶ Python worker
//	   ▲                              └─▶ Viewer（見ている間だけ）──▶ 管理画面（ブラウザがデコード）
//	   └── 状態（認識するか・何 fps で送るか）を、サーバーが決めて伝える
type StreamService struct {
	env     config.Env
	cameras *CameraService
	queue   *repository.QueueRepository

	mu      sync.Mutex
	devices map[string]*Device
}

func NewStreamService(env config.Env, cameras *CameraService, queue *repository.QueueRepository) *StreamService {
	return &StreamService{env: env, cameras: cameras, queue: queue, devices: map[string]*Device{}}
}

func (s *StreamService) device(id string) *Device {
	s.mu.Lock()
	defer s.mu.Unlock()
	d, ok := s.devices[id]
	if !ok {
		d = newDevice(id)
		s.devices[id] = d
	}
	return d
}

// SetRecognize は、管理画面の「認識を開始／停止」。接続中のスマホには、0.3 秒以内に伝わる。
func (s *StreamService) SetRecognize(cameraID string, on bool) {
	d := s.device(cameraID)
	d.mu.Lock()
	d.recognize = on
	d.mu.Unlock()
}

// SetLines は、管理画面で編集された「数える線」。接続中のスマホにも、0.3 秒以内に伝わる（スマホの画面にも、同じ線が出る）。
func (s *StreamService) SetLines(cameraID string, lines []byte) {
	d := s.device(cameraID)
	d.mu.Lock()
	d.lines = lines
	d.mu.Unlock()
}

// SetCameraSettings は、管理画面が決めたスマホのカメラの設定。接続中のスマホには、0.3 秒以内に伝わる。
func (s *StreamService) SetCameraSettings(cameraID string, raw []byte) {
	d := s.device(cameraID)
	d.mu.Lock()
	d.settings = raw
	d.mu.Unlock()
}

// Snapshot は、端末の受信の状況のコピー。
func (s *StreamService) Snapshot(cameraID string) Runtime {
	d := s.device(cameraID)
	d.mu.Lock()
	defer d.mu.Unlock()
	rt := d.rt
	rt.Active = d.phone != nil && !rt.LastSeen.IsZero() && time.Since(rt.LastSeen) < 3*time.Second
	return rt
}

// IsStreaming は、いま映像を受信しているか。
func (s *StreamService) IsStreaming(cameraID string) bool { return s.Snapshot(cameraID).Active }

// PhoneOnline は、スマホの送信ページが開いていて、サーバーからの指示を受けられるか。
func (s *StreamService) PhoneOnline(cameraID string) bool {
	d := s.device(cameraID)
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.phone != nil
}

// Sending は、認識用の映像が届いているか（認識中で、実際に届いている）。
func (s *StreamService) Sending(cameraID string) bool {
	d := s.device(cameraID)
	d.mu.Lock()
	rec := d.recognize
	d.mu.Unlock()
	return rec && s.Snapshot(cameraID).Active
}

// ---------------------------------------------------------------------------
// スマホとの接続（/ws/:id）：映像（バイナリ）を受け、状態（JSON）を伝える。1 台 1 本
// ---------------------------------------------------------------------------

// RunDevice は、スマホの接続 1 本を、切れるまで処理する。
func (s *StreamService) RunDevice(cameraID string, conn Conn) error {
	cam, err := s.cameras.Get(cameraID)
	if err != nil {
		return err
	}
	if cam == nil {
		return errNotFound("登録されていない端末")
	}
	d := s.device(cameraID)

	// 同じ端末の新しいページが開いたら、古い方を閉じる
	d.mu.Lock()
	old := d.phone
	// 認識中かは、DB の状態から（再起動のあとも、続きから再開できる）。yaml で固定した端末（テスト用）は、常に認識する
	d.phone, d.recognize = conn, cam.Recognizing || cam.Source == "yaml"
	d.settings, d.caps = []byte(cam.CameraSettings), nil
	d.lines, _ = json.Marshal(cam.Lines)
	d.mu.Unlock()
	if old != nil {
		_ = old.Close()
	}
	log.Printf("スマホが接続 %s（認識中=%v）", cameraID, cam.Recognizing)

	stop := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		s.control(d, cam.SampleFPS, conn, stop)
	}()
	defer func() {
		close(stop)
		wg.Wait()
		d.mu.Lock()
		if d.phone == conn {
			d.phone = nil
		}
		d.mu.Unlock()
		d.reset()
		log.Printf("スマホが切断 %s", cameraID)
	}()

	for {
		typ, data, err := conn.ReadMessage()
		if err != nil {
			return nil // 切断は、エラーではなく正常な終了として扱う
		}
		if typ == binaryMessage && len(data) > 0 {
			d.Publish(data)
		} else if typ == 1 && len(data) < 32<<10 && strings.HasPrefix(string(data), `{"caps"`) {
			// スマホからの報告：カメラの一覧・ズームの範囲・いまの設定（管理画面で選べるように、覚えておく）
			var m struct {
				Caps json.RawMessage `json:"caps"`
			}
			if json.Unmarshal(data, &m) == nil && len(m.Caps) > 2 {
				d.mu.Lock()
				d.caps = m.Caps
				d.mu.Unlock()
			}
		}
	}
}

// control は、0.3 秒ごとに「あるべき状態」を計算し、変わったときだけ、スマホに伝える（10 秒ごとにも、念のため）。
// 状態 = { recognize: 認識中か, send_fps: 何 fps で送るか（0 なら送らない）, idr: キーフレームを送り直す }
//   - 認識中なら、送る頻度は normal_fps。ライブ表示を見ている人がいれば、live_fps（高い方）。
//   - 一覧の小さな表示（thumb）を見ている人がいれば、thumb_fps（低い fps）。認識前でも、見られている間は送る。
//   - 認識中でなく、誰も見ていなければ、0（スマホは映像を送らない）。
//   - preview（見られているか）が false の間、スマホは送る解像度を落とす（認識には、元の解像度は要らない）。
//   - 認識の購読者（Recognizer）も、ここで、認識中かどうかに合わせて、登録・解除する。
func (s *StreamService) control(d *Device, sampleFPS float64, conn Conn, stop <-chan struct{}) {
	var (
		rec      *Recognizer
		lastSent struct {
			fps     float64
			rec     bool
			preview bool
			camera  string
			lines   string
		}
		sentAt time.Time
		joins  int
		first  = true
	)
	defer func() {
		if rec != nil {
			rec.Stop()
		}
	}()
	d.mu.Lock()
	joins = d.joins
	d.mu.Unlock()

	tick := time.NewTicker(300 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-stop:
			return
		case <-tick.C:
		}
		y, err := s.cameras.Yaml()
		if err != nil {
			continue
		}
		d.mu.Lock()
		want, viewers, thumbs, j, settings, lines := d.recognize, d.viewers, d.thumbs, d.joins, string(d.settings), string(d.lines)
		d.mu.Unlock()

		// 認識の購読者を、状態に合わせる
		if want && rec == nil {
			if r, err := StartRecognizer(d, sampleFPS, s.env, s.queue); err != nil {
				log.Printf("認識を始められない %s: %v", d.ID, err)
			} else {
				rec = r
			}
		} else if !want && rec != nil {
			rec.Stop()
			rec = nil
		}

		fps := 0.0
		if want {
			fps = y.Live.NormalFPS
		}
		if thumbs > 0 && fps < y.Live.ThumbFPS {
			fps = y.Live.ThumbFPS // 一覧に出ている間は、認識していなくても、低い fps で送る
		}
		if viewers > 0 && y.Live.LiveFPS > fps {
			fps = y.Live.LiveFPS
		}
		idr := j != joins // 誰かが新しく見始めた
		joins = j
		preview := viewers > 0 // 見られている間だけ、元の解像度で送る。見られていなければ、スマホは解像度を落とす
		if first || idr || fps != lastSent.fps || want != lastSent.rec || preview != lastSent.preview || settings != lastSent.camera || lines != lastSent.lines || time.Since(sentAt) > 10*time.Second {
			camera := json.RawMessage(`{}`)
			if len(settings) > 2 {
				camera = json.RawMessage(settings)
			}
			msg, _ := json.Marshal(map[string]any{"recognize": want, "send_fps": fps, "preview": preview, "idr": idr, "camera": camera, "lines": json.RawMessage(lines)})
			if conn.WriteText(string(msg)) != nil {
				return // 接続が閉じた
			}
			if first || fps != lastSent.fps || want != lastSent.rec || preview != lastSent.preview || idr {
				log.Printf("スマホに状態を伝えた %s: recognize=%v send_fps=%v preview=%v idr=%v", d.ID, want, fps, preview, idr)
			}
			lastSent.fps, lastSent.rec, lastSent.preview, lastSent.camera, lastSent.lines, sentAt, first = fps, want, preview, settings, lines, time.Now(), false
		}
	}
}

// ---------------------------------------------------------------------------
// 管理画面のライブ表示
// ---------------------------------------------------------------------------

// LiveInfo は、ライブ表示の画面に出す状況。
type LiveInfo struct {
	Streaming    bool            `json:"streaming"`     // 映像が届いている
	PhoneOnline  bool            `json:"phone_online"`  // スマホの送信ページが開いている（映像を送っていなくても）
	Recognizing  bool            `json:"recognizing"`   // 認識中か
	RxFPS        *float64        `json:"rx_fps"`        // 受信しているフレームレート
	LiveOn       bool            `json:"live_on"`       // 誰かがライブ表示を見ている
	RequestedFPS float64         `json:"requested_fps"` // 端末に頼む fps
	MaxSeconds   int             `json:"max_seconds"`
	Caps         json.RawMessage `json:"caps"` // スマホが報告した、カメラの能力（なければ null）
}

func (s *StreamService) LiveInfo(cameraID string) (LiveInfo, error) {
	y, err := s.cameras.Yaml()
	if err != nil {
		return LiveInfo{}, err
	}
	d := s.device(cameraID)
	rt := s.Snapshot(cameraID)
	d.mu.Lock()
	info := LiveInfo{
		Streaming: rt.Active, PhoneOnline: d.phone != nil, Recognizing: d.recognize, LiveOn: d.viewers > 0,
		RequestedFPS: y.Live.LiveFPS, MaxSeconds: y.Live.MaxSecond,
	}
	if len(d.caps) > 0 {
		info.Caps = json.RawMessage(d.caps)
	}
	d.mu.Unlock()
	if rt.Active {
		info.RxFPS = &rt.RxFPS
	}
	return info, nil
}

// Subscribe は、映像（H.264 の中継）を見始める。戻り値の cancel で、やめる。
// リアルタイム表示を見ている間は、スマホが高い fps（live_fps）で送る。thumb（一覧の小さな表示）なら、低い fps（thumb_fps）でよい。
func (s *StreamService) Subscribe(cameraID string, thumb bool) (*Viewer, func(), error) {
	cam, err := s.cameras.Get(cameraID)
	if err != nil {
		return nil, nil, err
	}
	if cam == nil {
		return nil, nil, errNotFound("登録されていない端末")
	}
	v, cancel := s.device(cameraID).AddViewer(thumb)
	return v, cancel, nil
}

// MaxLiveSeconds は、ライブ表示を続けられる上限（閉じ忘れ対策）。
func (s *StreamService) MaxLiveSeconds() time.Duration {
	if y, err := s.cameras.Yaml(); err == nil {
		return time.Duration(y.Live.MaxSecond) * time.Second
	}
	return 10 * time.Minute
}
