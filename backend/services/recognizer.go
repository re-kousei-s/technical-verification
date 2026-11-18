package services

import (
	"bytes"
	"context"
	"image"
	_ "image/jpeg" // image.DecodeConfig で JPEG の縦横を読むために必要
	"log"
	"sync"
	"time"

	"humandetect/config"
	"humandetect/repository"
)

// Recognizer は、認識に回すための購読者。届いた H.264 を ffmpeg でデコードし、
// 認識の頻度（sample_fps）に間引いて、Redis のキューに積む（Python の worker が取り出す）。
//
// H.264 は途中のフレームを捨てるとデコードできないので、全フレームをデコードしてから間引く。
type Recognizer struct {
	cameraID  string
	sampleFPS float64
	env       config.Env
	queue     *repository.QueueRepository
	dev       *Device

	mu     sync.Mutex
	dec    *Decoder
	jpegs  chan Frame // 送り方 jpeg のフレーム（デコードしない。そのまま、間引いて積む）
	stop   chan struct{}
	wg     sync.WaitGroup
	cancel func() // 購読をやめる
}

// StartRecognizer は、認識を始める（デバイスの購読者として登録される）。
func StartRecognizer(dev *Device, sampleFPS float64, env config.Env, queue *repository.QueueRepository) (*Recognizer, error) {
	r := &Recognizer{cameraID: dev.ID, sampleFPS: sampleFPS, env: env, queue: queue, dev: dev, stop: make(chan struct{}), jpegs: make(chan Frame, 16)}
	if err := r.startDecoder(); err != nil {
		return nil, err
	}
	r.cancel = dev.Subscribe(r.onChunk, true) // 覚えている GOP（最後のキーフレームから今まで）から始める。途中から受け取ると、キーフレームが来るまでデコードできない
	log.Printf("認識を開始 %s (sample_fps=%v)", dev.ID, sampleFPS)
	return r, nil
}

// Stop は、認識を止める。
func (r *Recognizer) Stop() {
	r.cancel()
	close(r.stop)
	r.mu.Lock()
	if r.dec != nil {
		r.dec.Close()
	}
	r.mu.Unlock()
	r.wg.Wait()
	log.Printf("認識を停止 %s", r.cameraID)
}

// onChunk は、チャンクを ffmpeg に渡す。ffmpeg が止まっていたら、起動し直す。
func (r *Recognizer) onChunk(c Chunk) {
	if c.JPEG { // JPEG は、デコードせずに、そのまま間引きへ
		select {
		case r.jpegs <- Frame{JPEG: c.Data, CapMs: c.CapMs}:
		default:
			r.dev.update(func(rt *Runtime) { rt.DecodeErrors++ }) // 間引きが追いつかず、捨てた
		}
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	select {
	case <-r.dec.Done():
		r.dec.Close()
		if err := r.startDecoderLocked(); err != nil {
			log.Printf("ffmpeg を起動し直せない %s: %v", r.cameraID, err)
			return
		}
	default:
	}
	if !r.dec.Write(c.Data, c.CapMs) {
		r.dev.update(func(rt *Runtime) { rt.DecodeErrors++ }) // デコーダが追いつかず、捨てた
	}
}

func (r *Recognizer) startDecoder() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.startDecoderLocked()
}

func (r *Recognizer) startDecoderLocked() error {
	dec, err := NewDecoder()
	if err != nil {
		return err
	}
	r.dec = dec
	r.wg.Add(1)
	go func() {
		defer r.wg.Done()
		r.sampleLoop(dec)
	}()
	return nil
}

// sampleLoop は、デコードされた JPEG を、認識に回す頻度（sample_fps）に間引いて、キューに積む。
//
// 時刻は、スマホで撮った時刻（サーバーの時計に直したもの）。届いた時刻ではないので、送信が遅れてまとめて届いても、間隔は崩れない。
// 一度見た撮影時刻以前のフレームは、捨てる（認識を始め直したときに、覚えている GOP を流し直す・同じ絵の送り直し で、二度処理しない）。
func (r *Recognizer) sampleLoop(dec *Decoder) {
	interval := time.Duration(float64(time.Second) / r.sampleFPS)
	// 採る時刻の目安（格子）を、interval ごとに進める。目安より early だけ早く届いたものまでは、採る。
	// 前に採った時刻からの間隔で決めると、スマホが、ちょうど sample_fps で送ってくるとき、少し早く届いたフレームを捨てて、
	// 次のフレーム（約 2 倍の間隔）を採ってしまい、実質の fps が半分になる（追跡が途切れる）。
	early := interval * 2 / 5
	var next time.Time
	partition := r.queue.PartitionOf(r.cameraID)
	var (
		frame Frame
		ok    bool
	)
	for {
		select {
		case <-r.stop:
			return
		case frame = <-r.jpegs:
		case frame, ok = <-dec.Frames():
			if !ok {
				return // ffmpeg が終わった
			}
		}
		{
			if !r.dev.claimFrame(frame.CapMs) {
				r.dev.update(func(rt *Runtime) { rt.Duplicates++ })
				continue // 処理済みのフレーム
			}
			jpeg := frame.JPEG
			now := time.Now()
			if frame.CapMs > 0 {
				now = time.UnixMilli(frame.CapMs)
			}
			if next.IsZero() {
				next = now
			}
			if now.Before(next.Add(-early)) {
				continue // 間引く（目安の時刻より、だいぶ早い）
			}
			next = next.Add(interval)
			if now.After(next.Add(interval)) {
				next = now.Add(interval) // 止まっていた（遅れすぎ）：目安を、いまから作り直す
			}
			// キューがあふれそうなら、新しいフレームを捨てる（worker が追いついていない目印）
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			if n, err := r.queue.Length(ctx, partition); err == nil && n >= int64(r.env.MaxQueue) {
				r.dev.update(func(rt *Runtime) { rt.Dropped++ })
				cancel()
				continue
			}
			w, h := jpegSize(jpeg)
			if err := r.queue.Enqueue(ctx, r.cameraID, now.UnixMilli(), w, h, jpeg); err != nil {
				log.Printf("キューに積めない %s: %v", r.cameraID, err)
			} else {
				r.dev.update(func(rt *Runtime) { rt.Enqueued++ })
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
