package services

import (
	"bufio"
	"bytes"
	"io"
	"log"
	"os/exec"
	"sync"
)

// Decoder は、ffmpeg を子プロセスとして動かし、H.264 を JPEG に直す。
//
//	H.264 のチャンク ─(標準入力)→ ffmpeg ─(標準出力)→ JPEG が 1 フレームずつ
//
// ffmpeg は全フレームをデコードして JPEG にする。間引くのは、そのあと（StreamService）。
// H.264 は途中のフレームを捨てるとデコードできないので、「デコードしてから間引く」のが正しい順序。
type Decoder struct {
	cmd    *exec.Cmd
	in     chan []byte   // ffmpeg に渡すチャンクの待ち行列
	frames chan []byte   // ffmpeg が出した JPEG
	done   chan struct{} // ffmpeg が終わったら閉じる
	once   sync.Once
}

// ffmpeg に渡す引数。遅れを小さくし、フレームを 1 枚も捨てない（-fps_mode passthrough）。
//
// 注意（実測で分かったこと）
//   - "-fflags nobuffer" は付けない。付けると、ffmpeg がフレームの大半を捨てる（64 枚中 14 枚しか出ない）。
//   - "-analyzeduration 0" は「解析しない」ではなく「既定（5 秒）」の意味。生の H.264 には時刻が無く、
//     ffmpeg は 25fps と仮定して 5 秒ぶん（= 125 フレーム）読むまで出力を始めない。5fps で送ってくる端末だと、
//     25 秒も画像が出てこない。そこで 1（= 最小）を指定する。
//   - "-fpsprobesize 0" は、フレームレートの推定のために、何枚も読んで待つのをやめる。
var ffmpegArgs = []string{
	"-hide_banner", "-loglevel", "error",
	"-flags", "low_delay",
	"-probesize", "32768", "-analyzeduration", "1", "-fpsprobesize", "0",
	"-f", "h264", "-i", "pipe:0", // 入力: 標準入力の H.264（Annex B）
	"-fps_mode", "passthrough",
	"-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "5", "pipe:1", // 出力: JPEG を標準出力へ
}

// NewDecoder は、ffmpeg を起動する。
func NewDecoder() (*Decoder, error) {
	cmd := exec.Command("ffmpeg", ffmpegArgs...)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	d := &Decoder{cmd: cmd, in: make(chan []byte, 256), frames: make(chan []byte, 16), done: make(chan struct{})}

	// 書く側：待ち行列のチャンクを、順に ffmpeg の標準入力へ
	go func() {
		for chunk := range d.in {
			if _, err := stdin.Write(chunk); err != nil {
				break
			}
		}
		stdin.Close()
	}()

	// 読む側：標準出力から JPEG を 1 枚ずつ切り出す
	go func() {
		defer close(d.done)
		defer close(d.frames)
		sc := bufio.NewScanner(stdout)
		sc.Buffer(make([]byte, 0, 1<<20), 16<<20)
		sc.Split(splitJPEG)
		for sc.Scan() {
			frame := append([]byte(nil), sc.Bytes()...) // Scanner のバッファは使い回されるのでコピーする
			select {
			case d.frames <- frame:
			default: // 受け取る側が詰まっている。古い方を諦める
			}
		}
	}()
	return d, nil
}

// Write は、チャンクを ffmpeg に渡す。待ち行列がいっぱいなら捨てて false を返す
// （ライブ中継を止めないため、ここで詰まらせない）。
func (d *Decoder) Write(chunk []byte) (ok bool) {
	defer func() { _ = recover() }() // Close 済みの in に送ると panic するので、握りつぶして false
	select {
	case d.in <- chunk:
		return true
	default:
		return false
	}
}

// Frames は、デコードできた JPEG が流れてくる通り道。ffmpeg が終わると閉じる。
func (d *Decoder) Frames() <-chan []byte { return d.frames }

// Done は、ffmpeg が終わった（または Close された）ら閉じる。
func (d *Decoder) Done() <-chan struct{} { return d.done }

// Close は、ffmpeg を止める。何度呼んでもよい。
func (d *Decoder) Close() {
	d.once.Do(func() {
		close(d.in)
		if d.cmd.Process != nil {
			if err := d.cmd.Process.Kill(); err != nil {
				log.Printf("ffmpeg を止められない: %v", err)
			}
		}
		go d.cmd.Wait() // 子プロセスの後始末（ゾンビにしない）
	})
}

// splitJPEG は、JPEG が続けて並んだ流れから、1 枚ずつ切り出す。
// JPEG の終わりは FF D9。データの途中の FF は FF 00 と書かれる決まりなので、FF D9 は終わりにしか現れない。
func splitJPEG(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if i := bytes.Index(data, []byte{0xff, 0xd9}); i >= 0 {
		return i + 2, data[:i+2], nil
	}
	if atEOF && len(data) > 0 {
		return len(data), nil, io.EOF
	}
	return 0, nil, nil // まだ 1 枚ぶん揃っていない。続きを待つ
}
