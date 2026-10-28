// Package models は、DB のテーブルと、API でやり取りするデータの形を定める。
//
// テーブルの作成は database/schema.sql が行う（ここでは AutoMigrate をしない）。
// 各構造体は、そのテーブルの 1 行に対応する。
package models

import (
	"database/sql/driver"
	"fmt"
	"time"
)

// JSON は、PostgreSQL の jsonb 列を、そのままのバイト列で持つ型。
// 中身（線やゲートの座標）の解釈は、使う側（services）が行う。
type JSON []byte

// Value は、DB に書くときの変換。
func (j JSON) Value() (driver.Value, error) {
	if len(j) == 0 {
		return "null", nil
	}
	return string(j), nil
}

// Scan は、DB から読むときの変換。
func (j *JSON) Scan(v any) error {
	switch t := v.(type) {
	case nil:
		*j = nil
	case []byte:
		*j = append((*j)[:0], t...)
	case string:
		*j = JSON(t)
	default:
		return fmt.Errorf("JSON: 想定外の型 %T", v)
	}
	return nil
}

// MarshalJSON は、レスポンスにそのまま埋め込むための変換（空なら null）。
func (j JSON) MarshalJSON() ([]byte, error) {
	if len(j) == 0 {
		return []byte("null"), nil
	}
	return j, nil
}

// ---------------------------------------------------------------------------
// テーブル
// ---------------------------------------------------------------------------

// Camera は、スマホなどの端末（= カメラ）の登録。cameras テーブル。
// NULL の項目は、cameras.yaml の defaults を使う。
type Camera struct {
	CameraID     string    `gorm:"column:camera_id;primaryKey"`
	Floor        int       `gorm:"column:floor"`
	Name         *string   `gorm:"column:name"`
	Lines        JSON      `gorm:"column:lines"` // カウントライン [{id,name,line:[[x1,y1],[x2,y2]]}, ...]  座標は画面に対する割合
	SampleFPS    *float64  `gorm:"column:sample_fps"`
	Anchor       *string   `gorm:"column:anchor"`
	Tracker      *string   `gorm:"column:tracker"`
	Tiling       *string   `gorm:"column:tiling"`
	Recognizing  bool      `gorm:"column:recognizing"` // 管理画面が「認識中」にしているか
	RegisteredAt time.Time `gorm:"column:registered_at"`
	UpdatedAt    time.Time `gorm:"column:updated_at"`
}

func (Camera) TableName() string { return "cameras" }

// CameraState は、端末ごとの累計 IN/OUT と、最後に処理したフレームの様子。camera_state テーブル。
type CameraState struct {
	CameraID    string     `gorm:"column:camera_id;primaryKey" json:"camera_id"`
	Floor       *int       `gorm:"column:floor" json:"floor"`
	InCount     int        `gorm:"column:in_count" json:"in_count"`
	OutCount    int        `gorm:"column:out_count" json:"out_count"`
	LastFrameTs *time.Time `gorm:"column:last_frame_ts" json:"last_frame_ts"`
	LastDets    *int       `gorm:"column:last_dets" json:"last_dets"`
	LastTracks  *int       `gorm:"column:last_tracks" json:"last_tracks"`
	FrameW      *int       `gorm:"column:frame_w" json:"frame_w"`
	FrameH      *int       `gorm:"column:frame_h" json:"frame_h"`
}

func (CameraState) TableName() string { return "camera_state" }

// FloorCount は、フロアの人数（前回 + IN − OUT、下限 0）。floor_counts テーブル。
type FloorCount struct {
	Floor       int        `gorm:"column:floor;primaryKey" json:"floor"`
	Count       int        `gorm:"column:count" json:"count"`
	UpdatedAt   time.Time  `gorm:"column:updated_at" json:"updated_at"`
	CorrectedAt *time.Time `gorm:"column:corrected_at" json:"corrected_at"` // 最後に人が補正した時刻
}

func (FloorCount) TableName() string { return "floor_counts" }

// Crossing は、線またはゲートでの通過 1 件。crossings テーブル。
type Crossing struct {
	ID        int64     `gorm:"column:id;primaryKey" json:"id"`
	CameraID  string    `gorm:"column:camera_id" json:"camera_id"`
	Floor     *int      `gorm:"column:floor" json:"floor"`
	Ts        time.Time `gorm:"column:ts" json:"ts"`
	Direction string    `gorm:"column:direction" json:"direction"` // "in" / "out"
	TrackID   int       `gorm:"column:track_id" json:"track_id"`
	LineName  *string   `gorm:"column:line_name" json:"line_name"` // どの線での通過か（線の名前）
}

func (Crossing) TableName() string { return "crossings" }

// ---------------------------------------------------------------------------
// API でやり取りする形
// ---------------------------------------------------------------------------

// Line は、カウントライン 1 本。人がこの線を越えた向きで IN / OUT を数える。
// line は [始点, 終点]（画面に対する割合）。IN の向きは、始点→終点に対して画面の左側。
// 入口が複数ある場合は、入口ごとに線を 1 本引く。
type Line struct {
	ID   string      `json:"id"`
	Name string      `json:"name"`
	Line [][]float64 `json:"line"`
}

// CameraConfig は、yaml の既定値を埋めた、端末 1 台ぶんの設定（API にそのまま返す）。
type CameraConfig struct {
	ID        string  `json:"id"`
	Floor     int     `json:"floor"`
	Name      *string `json:"name"`
	Lines     []Line  `json:"lines"`
	SampleFPS float64 `json:"sample_fps"`
	Tracker   string  `json:"tracker"`
	Anchor    string  `json:"anchor"`
	Tiling    string  `json:"tiling"`
	Source    string  `json:"source"` // "db"（送信ページから登録）/ "yaml"（固定）
	// 認識中か。スマホは、これが true の間だけ映像を送る（管理画面が決める）
	Recognizing bool `json:"recognizing"`
}
