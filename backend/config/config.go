// Package config は、バックエンドの設定を読み込む。
//
// 設定は2か所から来る：
//   - 環境変数  … 接続先（DB・Redis・ポート）など、環境ごとに変わるもの
//   - cameras.yaml … カメラの既定値、フロアのしきい値、ライブ表示のパラメータなど
//     （Python の worker も同じファイルを読む。リクエストのたびに読み直すので、再起動なしで反映される）
package config

import (
	"os"
	"strconv"

	"gopkg.in/yaml.v3"
)

// Env は環境変数から読む設定。
type Env struct {
	DatabaseURL string // PostgreSQL の接続先
	RedisURL    string // Redis の接続先（キューと、worker の結果の受け渡し）
	CamerasPath string // cameras.yaml の場所
	DeviceAddr  string // スマホ向け（送信ページ・WebSocket・登録 API）の待ち受け
	AdminAddr   string // 管理画面向けの待ち受け
	Partitions  int    // キューの分割数（カメラを何本の worker に振り分けるか）
	MaxQueue    int    // キューに溜められる上限（超えたら新しいフレームを捨てる）
}

// LoadEnv は環境変数を読み、無いものには既定値を入れる。
func LoadEnv() Env {
	return Env{
		DatabaseURL: get("DATABASE_URL", "postgresql://hdt:hdt@postgres:5432/hdt"),
		RedisURL:    get("REDIS_URL", "redis://redis:6379/0"),
		CamerasPath: get("CAMERAS_PATH", "/config/cameras.yaml"),
		DeviceAddr:  get("DEVICE_ADDR", ":8000"),
		AdminAddr:   get("ADMIN_ADDR", ":8080"),
		Partitions:  getInt("PARTITIONS", 1),
		MaxQueue:    getInt("MAX_QUEUE", 200),
	}
}

func get(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getInt(key string, def int) int {
	if v, err := strconv.Atoi(os.Getenv(key)); err == nil {
		return v
	}
	return def
}

// ---------------------------------------------------------------------------
// cameras.yaml
// ---------------------------------------------------------------------------

// Yaml は cameras.yaml の中身のうち、バックエンドが使う部分。
type Yaml struct {
	Defaults struct {
		SampleFPS float64 `yaml:"sample_fps"` // 認識に回す、1秒あたりの枚数
		Tracker   string  `yaml:"tracker"`
		Anchor    string  `yaml:"anchor"`
		Tiling    string  `yaml:"tiling"`
	} `yaml:"defaults"`
	Live struct {
		NormalFPS float64 `yaml:"normal_fps"` // ふだん端末が送る fps
		LiveFPS   float64 `yaml:"live_fps"`   // ライブ表示中に端末へ頼む fps
		MaxSecond int     `yaml:"max_seconds"`
	} `yaml:"live"`
	Estimate struct {
		ErrorRate float64 `yaml:"error_rate"` // 概算の誤差率（通過 1 件あたり）
	} `yaml:"estimate"`
	Floors  map[int]Threshold `yaml:"floors"` // フロアごとの混雑のしきい値
	Cameras []YamlCamera      `yaml:"cameras"`
}

// Threshold は、フロア人数の「黄」「赤」になる人数。
type Threshold struct {
	Yellow int `yaml:"yellow" json:"yellow"`
	Red    int `yaml:"red" json:"red"`
}

// YamlCamera は、yaml に書いた固定のカメラ（テスト用など）。
// 線は、複数なら lines:（名前つきのリスト）、1 本だけなら line: と書ける。
type YamlCamera struct {
	ID    string      `yaml:"id"`
	Floor int         `yaml:"floor"`
	Line  [][]float64 `yaml:"line"`
	Lines []YamlLine  `yaml:"lines"`
}

// YamlLine は、yaml に書いた線 1 本（名前と座標）。
type YamlLine struct {
	Name string      `yaml:"name"`
	Line [][]float64 `yaml:"line"`
}

// LoadYaml は cameras.yaml を読む。足りない値には既定値を入れる。
func LoadYaml(path string) (*Yaml, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	y := &Yaml{}
	if err := yaml.Unmarshal(raw, y); err != nil {
		return nil, err
	}
	if y.Defaults.SampleFPS == 0 {
		y.Defaults.SampleFPS = 5
	}
	if y.Defaults.Tracker == "" {
		y.Defaults.Tracker = "lowfps"
	}
	if y.Defaults.Anchor == "" {
		y.Defaults.Anchor = "top_center"
	}
	if y.Defaults.Tiling == "" {
		y.Defaults.Tiling = "none"
	}
	if y.Live.NormalFPS == 0 {
		y.Live.NormalFPS = 5
	}
	if y.Live.LiveFPS == 0 {
		y.Live.LiveFPS = 15
	}
	if y.Live.MaxSecond == 0 {
		y.Live.MaxSecond = 600
	}
	if y.Estimate.ErrorRate == 0 {
		y.Estimate.ErrorRate = 0.2
	}
	return y, nil
}
