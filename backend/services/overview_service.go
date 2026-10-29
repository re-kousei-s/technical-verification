package services

import (
	"context"
	"fmt"
	"sort"
	"time"

	"humandetect/models"
	"humandetect/repository"
)

// staleAfter より古いハートビートは「止まっている」とみなす。
const staleAfter = 15 * time.Second

// OverviewService は、管理画面の一覧に出す情報を、1 つにまとめる。
// DB（人数・履歴）、Redis（キュー・worker・検出枠つき画像）、メモリ（受信の状況）を読み合わせる。
type OverviewService struct {
	db      *repository.DBRepository
	queue   *repository.QueueRepository
	cameras *CameraService
	streams *StreamService
}

func NewOverviewService(db *repository.DBRepository, queue *repository.QueueRepository,
	cameras *CameraService, streams *StreamService) *OverviewService {
	return &OverviewService{db: db, queue: queue, cameras: cameras, streams: streams}
}

// ---- 画面に返す形（JSON のキー名は、管理画面の JavaScript と合わせてある） ----

type ServiceStatus struct {
	Redis        bool `json:"redis"`
	Postgres     bool `json:"postgres"`
	Backend      bool `json:"ingest"` // 画面では「ingest」と表示している（= このバックエンド）
	WorkersAlive int  `json:"workers_alive"`
	WorkersTotal int  `json:"workers_total"`
}

type CameraView struct {
	ID            string     `json:"id"`
	Floor         int        `json:"floor"`
	Name          *string    `json:"name"`
	SampleFPS     float64    `json:"sample_fps"`
	Tracker       string     `json:"tracker"`
	Anchor        string     `json:"anchor"`
	Lines         []string   `json:"lines"`        // 線の名前だけ
	Recognizing   bool       `json:"recognizing"`  // 管理画面が「認識中」にしているか
	PhoneOnline   bool       `json:"phone_online"` // スマホの送信ページが開いていて、指示を受けられるか
	Source        string     `json:"source"`       // "db"（スマホから登録・編集できる）／ "yaml"（固定。編集不可）
	Connected     bool       `json:"connected"`
	LastSeenAgeMs *int64     `json:"last_seen_age_ms"`
	Decoded       int64      `json:"decoded"`
	Enqueued      int64      `json:"enqueued"`
	Dropped       int64      `json:"dropped"`
	DecodeErrors  int64      `json:"decode_errors"`
	In            int        `json:"in"`
	Out           int        `json:"out"`
	LastDets      *int       `json:"last_dets"`
	LastTracks    *int       `json:"last_tracks"`
	LastFrameTs   *time.Time `json:"last_frame_ts"`
	Size          [2]*int    `json:"size"`
	HasImage      bool       `json:"has_image"`
}

type FloorDevice struct {
	ID        string  `json:"id"`
	Name      *string `json:"name"`
	Connected bool    `json:"connected"`
	In        int     `json:"in"`
	Out       int     `json:"out"`
}

type FloorView struct {
	Floor                   int           `json:"floor"`
	Count                   int           `json:"count"`
	Low                     int           `json:"low"`
	High                    int           `json:"high"`
	Margin                  int           `json:"margin"`
	CrossingsSinceCorrected int           `json:"crossings_since_correction"`
	CorrectedAt             *time.Time    `json:"corrected_at"`
	Level                   *string       `json:"level"` // blue / yellow / red（しきい値が無ければ null）
	Thresholds              any           `json:"thresholds"`
	UpdatedAt               *time.Time    `json:"updated_at"`
	Cameras                 []FloorDevice `json:"cameras"`
}

type Overview struct {
	NowMs           int64                   `json:"now_ms"`
	Services        ServiceStatus           `json:"services"`
	Problems        []string                `json:"problems"`
	Queue           []repository.QueueInfo  `json:"queue"`
	Backlog         int64                   `json:"backlog"`
	Workers         []repository.WorkerInfo `json:"workers"`
	Cameras         []CameraView            `json:"cameras"`
	LiveFPS         float64                 `json:"live_fps"`
	Floors          []FloorView             `json:"floors"`
	RecentCrossings []models.Crossing       `json:"recent_crossings"`
	Perf60s         repository.Perf         `json:"perf_60s"`
	Totals          repository.Totals       `json:"totals"`
}

// Build は、管理画面に出す情報を組み立てる。
func (s *OverviewService) Build(ctx context.Context) (*Overview, error) {
	y, err := s.cameras.Yaml()
	if err != nil {
		return nil, err
	}
	cams, err := s.cameras.All()
	if err != nil {
		return nil, err
	}
	o := &Overview{NowMs: time.Now().UnixMilli(), Problems: []string{}, LiveFPS: y.Live.LiveFPS,
		Cameras: []CameraView{}, Floors: []FloorView{}, RecentCrossings: []models.Crossing{}}

	// --- Redis / worker / キュー ---
	o.Services.Redis = s.queue.Ping(ctx) == nil
	o.Services.Backend = true
	if o.Services.Redis {
		o.Queue = s.queue.Queues(ctx)
		o.Workers = s.queue.Workers(ctx, staleAfter)
		for _, q := range o.Queue {
			o.Backlog += q.Length
		}
		for _, w := range o.Workers {
			if w.Alive {
				o.Services.WorkersAlive++
			}
		}
		o.Services.WorkersTotal = len(o.Workers)
		if o.Services.WorkersAlive == 0 {
			msg := "worker が動いていない"
			if o.Backlog > 0 {
				msg += "（キューが溜まっている）"
			}
			o.Problems = append(o.Problems, msg)
		}
	} else {
		o.Problems = append(o.Problems, "Redis に接続できない")
	}

	// --- DB ---
	states, floors, sinceCorrection := map[string]models.CameraState{}, map[int]models.FloorCount{}, map[int]int{}
	if err := s.db.Ping(); err != nil {
		o.Problems = append(o.Problems, fmt.Sprintf("DB に接続できない: %v", err))
	} else {
		o.Services.Postgres = true
		states, _ = s.db.CameraStates()
		floors, _ = s.db.FloorCounts()
		sinceCorrection, _ = s.db.CrossingsSinceCorrection()
		if rows, err := s.db.RecentCrossings(30, ""); err == nil && rows != nil {
			o.RecentCrossings = rows
		}
		o.Perf60s, _ = s.db.Perf60s()
		o.Totals, _ = s.db.Totals()
	}

	// --- 端末ごと ---
	for _, c := range cams {
		rt := s.streams.Snapshot(c.ID)
		st := states[c.ID]
		names := make([]string, 0, len(c.Lines))
		for _, l := range c.Lines {
			names = append(names, l.Name)
		}
		v := CameraView{
			ID: c.ID, Floor: c.Floor, Name: c.Name, SampleFPS: c.SampleFPS, Tracker: c.Tracker, Anchor: c.Anchor,
			Lines: names, Source: c.Source, Recognizing: c.Recognizing, PhoneOnline: s.streams.PhoneOnline(c.ID), Connected: s.streams.Sending(c.ID),
			Decoded: rt.Decoded, Enqueued: rt.Enqueued, Dropped: rt.Dropped, DecodeErrors: rt.DecodeErrors,
			In: st.InCount, Out: st.OutCount, LastDets: st.LastDets, LastTracks: st.LastTracks,
			LastFrameTs: st.LastFrameTs, Size: [2]*int{st.FrameW, st.FrameH},
			HasImage: o.Services.Redis && s.queue.HasAnnotated(ctx, c.ID),
		}
		if !rt.LastSeen.IsZero() {
			age := time.Since(rt.LastSeen).Milliseconds()
			v.LastSeenAgeMs = &age
		}
		if rt.Dropped > 0 {
			o.Problems = append(o.Problems,
				fmt.Sprintf("%s: キューあふれでフレームを %d 枚捨てた（worker が追いついていない）", c.ID, rt.Dropped))
		}
		o.Cameras = append(o.Cameras, v)
	}

	// --- フロアごと：概算 = IN − OUT の合算。範囲 = 補正してからの通過件数 × 誤差率 ---
	ids := map[int]bool{}
	for _, c := range o.Cameras {
		ids[c.Floor] = true
	}
	for f := range floors {
		ids[f] = true
	}
	floorIDs := make([]int, 0, len(ids))
	for f := range ids {
		floorIDs = append(floorIDs, f)
	}
	sort.Ints(floorIDs)

	for _, f := range floorIDs {
		fc := floors[f]
		n := sinceCorrection[f]
		margin := EstimateMargin(n, y.Estimate.ErrorRate)
		fv := FloorView{Floor: f, Count: fc.Count, Low: max(0, fc.Count-margin), High: fc.Count + margin,
			Margin: margin, CrossingsSinceCorrected: n, CorrectedAt: fc.CorrectedAt, Cameras: []FloorDevice{}}
		if !fc.UpdatedAt.IsZero() {
			t := fc.UpdatedAt
			fv.UpdatedAt = &t
		}
		if th, ok := y.Floors[f]; ok { // しきい値があれば、青・黄・赤に分ける
			level := "blue"
			if fc.Count >= th.Red {
				level = "red"
			} else if fc.Count >= th.Yellow {
				level = "yellow"
			}
			fv.Level, fv.Thresholds = &level, th
		}
		for _, c := range o.Cameras {
			if c.Floor == f {
				fv.Cameras = append(fv.Cameras, FloorDevice{ID: c.ID, Name: c.Name, Connected: c.Connected, In: c.In, Out: c.Out})
			}
		}
		o.Floors = append(o.Floors, fv)
	}
	return o, nil
}
