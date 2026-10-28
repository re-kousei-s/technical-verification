package services

import (
	"math"

	"humandetect/repository"
)

// FloorService は、フロアの人数の概算と、人による補正・リセットを扱う。
//
// 概算値 = そのフロアの全端末の IN − OUT の合算（下限 0）。worker が通過のたびに floor_counts を更新する。
// 範囲   = 「人が補正してから今までの通過件数 × 誤差率」を ± にする。通過が増えるほど、誤差がたまる想定。
type FloorService struct {
	repo    *repository.DBRepository
	cameras *CameraService
}

func NewFloorService(repo *repository.DBRepository, cameras *CameraService) *FloorService {
	return &FloorService{repo: repo, cameras: cameras}
}

// EstimateMargin は、概算の「±」の幅。通過件数 × 誤差率を切り上げる。
func EstimateMargin(crossings int, errorRate float64) int {
	return int(math.Ceil(float64(crossings) * errorRate))
}

// Estimate は、フロア 1 つの概算（スマホの画面に出す）。
type Estimate struct {
	Count     int `json:"count"`
	Low       int `json:"low"`
	High      int `json:"high"`
	Crossings int `json:"crossings"` // 補正してから今までの通過件数
}

func (s *FloorService) Estimate(floor int) (Estimate, error) {
	y, err := s.cameras.Yaml()
	if err != nil {
		return Estimate{}, err
	}
	fc, err := s.repo.FloorCount(floor)
	if err != nil {
		return Estimate{}, err
	}
	n, err := s.repo.CountCrossings(floor, fc.CorrectedAt) // 補正が無ければ全期間
	if err != nil {
		return Estimate{}, err
	}
	m := EstimateMargin(n, y.Estimate.ErrorRate)
	return Estimate{Count: fc.Count, Low: max(0, fc.Count-m), High: fc.Count + m, Crossings: n}, nil
}

// SetCount は、スタッフによる人数の補正。
func (s *FloorService) SetCount(floor, count int) error {
	if count < 0 || count > 100000 {
		return errInvalid("人数は 0 以上の整数で指定する")
	}
	return s.repo.SetFloorCount(floor, count)
}

// ResetFloors は、全フロアの人数を 0 に戻す（閉場）。
func (s *FloorService) ResetFloors() (int64, error) { return s.repo.ResetFloors() }

// ResetHistory は、IN/OUT の履歴を消す。cameraID と floor は、どちらか一方だけ指定できる。
func (s *FloorService) ResetHistory(cameraID string, floor *int) (int64, error) {
	if cameraID != "" && floor != nil {
		return 0, errInvalid("camera_id と floor は同時に指定できない")
	}
	return s.repo.ResetHistory(cameraID, floor)
}

// ResetAll は、全部リセット：全端末の履歴と、全フロアの人数。
func (s *FloorService) ResetAll() (map[string]int64, error) {
	deleted, err := s.repo.ResetHistory("", nil)
	if err != nil {
		return nil, err
	}
	floors, err := s.repo.ResetFloors()
	return map[string]int64{"deleted_crossings": deleted, "floors_reset": floors}, err
}
