// Package repository は、DB（PostgreSQL）と Redis へのアクセスだけを担当する。
// 「何をどう読み書きするか」の業務ルールは、ここには書かない（services に書く）。
package repository

import (
	"time"

	"gorm.io/gorm"

	"humandetect/models"
)

// DBRepository は、PostgreSQL の読み書き（gorm）。
type DBRepository struct {
	db *gorm.DB
}

func NewDBRepository(db *gorm.DB) *DBRepository { return &DBRepository{db: db} }

// Ping は、DB につながるかを確かめる（管理画面の状態表示用）。
func (r *DBRepository) Ping() error {
	sqlDB, err := r.db.DB()
	if err != nil {
		return err
	}
	return sqlDB.Ping()
}

// ---------------------------------------------------------------------------
// cameras（端末の登録）
// ---------------------------------------------------------------------------

func (r *DBRepository) ListCameras() ([]models.Camera, error) {
	var rows []models.Camera
	err := r.db.Order("floor, camera_id").Find(&rows).Error
	return rows, err
}

func (r *DBRepository) CreateCamera(c *models.Camera) error { return r.db.Create(c).Error }

// UpdateCamera は、指定した列だけを更新する（例: {"line": ..., "sample_fps": ...}）。
func (r *DBRepository) UpdateCamera(id string, cols map[string]any) error {
	cols["updated_at"] = time.Now()
	return r.db.Model(&models.Camera{}).Where("camera_id = ?", id).Updates(cols).Error
}

func (r *DBRepository) DeleteCamera(id string) error {
	return r.db.Where("camera_id = ?", id).Delete(&models.Camera{}).Error
}

// ---------------------------------------------------------------------------
// camera_state / floor_counts / crossings（worker が書き、ここでは読む）
// ---------------------------------------------------------------------------

// CameraStates は、端末 ID → 累計 IN/OUT などの対応表。
func (r *DBRepository) CameraStates() (map[string]models.CameraState, error) {
	var rows []models.CameraState
	if err := r.db.Find(&rows).Error; err != nil {
		return nil, err
	}
	out := make(map[string]models.CameraState, len(rows))
	for _, s := range rows {
		out[s.CameraID] = s
	}
	return out, nil
}

func (r *DBRepository) CameraState(id string) (models.CameraState, error) {
	var s models.CameraState
	err := r.db.Where("camera_id = ?", id).Limit(1).Find(&s).Error // 無ければゼロ値
	return s, err
}

// FloorCounts は、フロア → 人数の対応表。
func (r *DBRepository) FloorCounts() (map[int]models.FloorCount, error) {
	var rows []models.FloorCount
	if err := r.db.Order("floor").Find(&rows).Error; err != nil {
		return nil, err
	}
	out := make(map[int]models.FloorCount, len(rows))
	for _, f := range rows {
		out[f.Floor] = f
	}
	return out, nil
}

// CrossingsSinceCorrection は、フロアごとの「人が補正してから今までの通過件数」。
// 一度も補正していなければ、全期間の件数。概算値の誤差の範囲に使う。
func (r *DBRepository) CrossingsSinceCorrection() (map[int]int, error) {
	type row struct {
		Floor int
		N     int
	}
	var rows []row
	err := r.db.Raw(`
		SELECT c.floor AS floor, count(*) AS n
		FROM crossings c LEFT JOIN floor_counts f ON f.floor = c.floor
		WHERE f.corrected_at IS NULL OR c.ts > f.corrected_at
		GROUP BY c.floor`).Scan(&rows).Error
	out := make(map[int]int, len(rows))
	for _, x := range rows {
		out[x.Floor] = x.N
	}
	return out, err
}

// RecentCrossings は、新しい順の通過の履歴。cameraID が空なら全端末。
func (r *DBRepository) RecentCrossings(limit int, cameraID string) ([]models.Crossing, error) {
	var rows []models.Crossing
	q := r.db.Order("id DESC").Limit(limit)
	if cameraID != "" {
		q = q.Where("camera_id = ?", cameraID)
	}
	return rows, q.Find(&rows).Error
}

// LineCount は、線ごとの IN/OUT の件数。
type LineCount struct {
	In  int `json:"in"`
	Out int `json:"out"`
}

// LineCounts は、端末の線の名前 → IN/OUT の件数。
func (r *DBRepository) LineCounts(cameraID string) (map[string]LineCount, error) {
	type row struct {
		LineName  string
		Direction string
		N         int
	}
	var rows []row
	err := r.db.Raw(`SELECT line_name, direction, count(*) AS n FROM crossings
		WHERE camera_id = ? AND line_name IS NOT NULL GROUP BY line_name, direction`, cameraID).Scan(&rows).Error
	out := map[string]LineCount{}
	for _, x := range rows {
		c := out[x.LineName]
		if x.Direction == "in" {
			c.In = x.N
		} else {
			c.Out = x.N
		}
		out[x.LineName] = c
	}
	return out, err
}

// Perf は、直近 60 秒の処理の統計（frame_log から）。
type Perf struct {
	Frames   int      `json:"frames"`
	InferAvg *float64 `json:"infer_avg"`
	InferP95 *float64 `json:"infer_p95"`
	LagAvg   *float64 `json:"lag_avg"`
	LagP95   *float64 `json:"lag_p95"`
	DetsAvg  *float64 `json:"dets_avg"`
}

func (r *DBRepository) Perf60s() (Perf, error) {
	var p Perf
	err := r.db.Raw(`SELECT count(*) AS frames, avg(infer_ms) AS infer_avg,
		percentile_cont(0.95) WITHIN GROUP (ORDER BY infer_ms) AS infer_p95,
		avg(lag_ms) AS lag_avg, percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_ms) AS lag_p95,
		avg(n_dets) AS dets_avg FROM frame_log WHERE created_at > now() - interval '60 seconds'`).Scan(&p).Error
	return p, err
}

// Totals は、通過とフレームの累計件数。
type Totals struct {
	Crossings int `json:"crossings"`
	Frames    int `json:"frames"`
}

func (r *DBRepository) Totals() (Totals, error) {
	var t Totals
	err := r.db.Raw(`SELECT (SELECT count(*) FROM crossings) AS crossings,
		(SELECT count(*) FROM frame_log) AS frames`).Scan(&t).Error
	return t, err
}

// CountCrossings は、フロアの（補正以降の）通過件数。since が nil なら全期間。
func (r *DBRepository) CountCrossings(floor int, since *time.Time) (int, error) {
	var n int64
	q := r.db.Model(&models.Crossing{}).Where("floor = ?", floor)
	if since != nil {
		q = q.Where("ts > ?", *since)
	}
	return int(n), q.Count(&n).Error
}

func (r *DBRepository) FloorCount(floor int) (models.FloorCount, error) {
	var f models.FloorCount
	err := r.db.Where("floor = ?", floor).Limit(1).Find(&f).Error // 無ければゼロ値
	return f, err
}

// ---------------------------------------------------------------------------
// 補正・リセット（人が操作する）
// ---------------------------------------------------------------------------

// SetFloorCount は、スタッフによる人数の補正。以降の通過件数は、この時刻から数え直す。
func (r *DBRepository) SetFloorCount(floor, count int) error {
	return r.db.Exec(`INSERT INTO floor_counts (floor, count, updated_at, corrected_at) VALUES (?, ?, now(), now())
		ON CONFLICT (floor) DO UPDATE SET count = EXCLUDED.count, updated_at = now(), corrected_at = now()`,
		floor, count).Error
}

// ResetFloors は、全フロアの人数を 0 に戻す（閉場）。戻したフロアの数を返す。
func (r *DBRepository) ResetFloors() (int64, error) {
	res := r.db.Exec(`UPDATE floor_counts SET count = 0, updated_at = now(), corrected_at = now()`)
	return res.RowsAffected, res.Error
}

// ResetHistory は、通過の履歴と、端末ごとの累計 IN/OUT を消す。
// cameraID か floor で範囲を絞れる（どちらも空なら全部）。消した通過の件数を返す。
// フロア人数の概算（floor_counts）は変えない。
func (r *DBRepository) ResetHistory(cameraID string, floor *int) (int64, error) {
	where, args := "", []any{}
	if cameraID != "" {
		where, args = " WHERE camera_id = ?", []any{cameraID}
	} else if floor != nil {
		where, args = " WHERE floor = ?", []any{*floor}
	}
	var deleted int64
	err := r.db.Transaction(func(tx *gorm.DB) error {
		res := tx.Exec("DELETE FROM crossings"+where, args...)
		if res.Error != nil {
			return res.Error
		}
		deleted = res.RowsAffected
		return tx.Exec("UPDATE camera_state SET in_count = 0, out_count = 0, updated_at = now()"+where, args...).Error
	})
	return deleted, err
}
