package services

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"humandetect/config"
	"humandetect/models"
	"humandetect/repository"
)

// CameraService は、端末（= カメラ）の登録と設定を扱う。
//
// 端末は 2 か所にある：
//   - cameras.yaml に書いた固定のカメラ（テスト用）… 変更・削除できない
//   - 送信ページから登録した端末（DB の cameras テーブル）
//
// この 2 つを合わせ、yaml の defaults で空欄を埋めたものを CameraConfig として返す。
type CameraService struct {
	repo     *repository.DBRepository
	yamlPath string
}

func NewCameraService(repo *repository.DBRepository, yamlPath string) *CameraService {
	return &CameraService{repo: repo, yamlPath: yamlPath}
}

// Yaml は cameras.yaml を読む（呼ぶたびに読み直す。再起動なしで設定が反映される）。
func (s *CameraService) Yaml() (*config.Yaml, error) { return config.LoadYaml(s.yamlPath) }

// All は、全端末の設定（フロア順、同じフロアなら ID 順）。
func (s *CameraService) All() ([]models.CameraConfig, error) {
	y, err := s.Yaml()
	if err != nil {
		return nil, err
	}
	byID := map[string]models.CameraConfig{}

	// 1) yaml の固定カメラ
	for _, c := range y.Cameras {
		byID[c.ID] = models.CameraConfig{
			ID: c.ID, Floor: c.Floor, Lines: yamlLines(c),
			SampleFPS: y.Defaults.SampleFPS, Tracker: y.Defaults.Tracker, Anchor: y.Defaults.Anchor,
			Tiling: y.Defaults.Tiling, Source: "yaml",
		}
	}

	// 2) DB に登録された端末（同じ ID があれば、こちらが優先）
	rows, err := s.repo.ListCameras()
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		c := models.CameraConfig{
			ID: r.CameraID, Floor: r.Floor, Name: r.Name, Lines: []models.Line{},
			SampleFPS: y.Defaults.SampleFPS, Tracker: y.Defaults.Tracker, Anchor: y.Defaults.Anchor,
			Tiling: y.Defaults.Tiling, Source: "db", Recognizing: r.Recognizing, CameraSettings: json.RawMessage(`{}`),
		}
		if len(r.CameraSettings) > 2 {
			c.CameraSettings = json.RawMessage(r.CameraSettings)
		}
		_ = json.Unmarshal(r.Lines, &c.Lines)
		if c.Lines == nil {
			c.Lines = []models.Line{}
		}
		// 個別に指定された項目だけ、既定値を上書きする
		if r.SampleFPS != nil {
			c.SampleFPS = *r.SampleFPS
		}
		if r.Tracker != nil {
			c.Tracker = *r.Tracker
		}
		if r.Anchor != nil {
			c.Anchor = *r.Anchor
		}
		if r.Tiling != nil {
			c.Tiling = *r.Tiling
		}
		byID[c.ID] = c
	}

	out := make([]models.CameraConfig, 0, len(byID))
	for _, c := range byID {
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Floor != out[j].Floor {
			return out[i].Floor < out[j].Floor
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}

// yamlLines は、yaml のカメラの線を、API で使う形にする。lines: があればそれを、無ければ line: を 1 本目として使う。
func yamlLines(c config.YamlCamera) []models.Line {
	if len(c.Lines) == 0 {
		return []models.Line{{ID: "l1", Name: "線1", Line: c.Line}}
	}
	out := make([]models.Line, 0, len(c.Lines))
	for i, l := range c.Lines {
		name := l.Name
		if name == "" {
			name = fmt.Sprintf("線%d", i+1)
		}
		out = append(out, models.Line{ID: fmt.Sprintf("l%d", i+1), Name: name, Line: l.Line})
	}
	return out
}

// Get は、端末 1 台の設定。登録が無ければ nil。
func (s *CameraService) Get(id string) (*models.CameraConfig, error) {
	all, err := s.All()
	if err != nil {
		return nil, err
	}
	for i := range all {
		if all[i].ID == id {
			return &all[i], nil
		}
	}
	return nil, nil
}

// mustGet は、登録が無ければ「404」のエラーにする。
func (s *CameraService) mustGet(id string) (*models.CameraConfig, error) {
	c, err := s.Get(id)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, errNotFound("登録されていない端末")
	}
	return c, nil
}

// Register は、端末を新しく登録する。端末 ID は「F{階}-{ランダム4文字}」。線の初期値は画面の中央の横線。
func (s *CameraService) Register(floor int, name string) (*models.CameraConfig, error) {
	if floor < -9 || floor > 99 {
		return nil, errInvalid("フロアは -9〜99 で指定する")
	}
	name = strings.TrimSpace(name)
	if len([]rune(name)) > 30 {
		return nil, errInvalid("名前は 30 文字まで")
	}
	b := make([]byte, 2)
	_, _ = rand.Read(b)
	cam := &models.Camera{
		CameraID: fmt.Sprintf("F%d-%s", floor, strings.ToUpper(hex.EncodeToString(b))),
		Floor:    floor,
		// 最初は、画面の中央に横線を 1 本（あとから動かしたり、増やしたりできる）
		Lines:          models.JSON(`[{"id":"l1","name":"線1","line":[[0,0.5],[1,0.5]]}]`),
		CameraSettings: models.JSON(`{}`), // カメラの設定は、空（スマホの既定）。NULL にしない
		RegisteredAt:   time.Now(),
	}
	if name != "" {
		cam.Name = &name
	}
	if err := s.repo.CreateCamera(cam); err != nil {
		return nil, err
	}
	return s.mustGet(cam.CameraID)
}

// CameraPatch は、端末の設定変更。指定した項目だけが変わる。
type CameraPatch struct {
	Lines     *[]models.Line `json:"lines"`
	SampleFPS *float64       `json:"sample_fps"`
	Anchor    *string        `json:"anchor"` // 線を越えたかの判定（box＝枠全体 / bottom_center / top_center / center）
}

// Update は、線・認識の頻度・判定する位置を変える。yaml の固定カメラは変えられない。
func (s *CameraService) Update(id string, p CameraPatch) (*models.CameraConfig, error) {
	cam, err := s.mustGet(id)
	if err != nil {
		return nil, err
	}
	if cam.Source != "db" {
		return nil, errConflict("yaml で固定したカメラは、ここでは変更できない")
	}
	cols := map[string]any{}
	if p.Lines != nil {
		lines, err := validateLines(*p.Lines)
		if err != nil {
			return nil, err
		}
		b, _ := json.Marshal(lines)
		cols["lines"] = models.JSON(b)
	}
	if p.Anchor != nil {
		switch *p.Anchor {
		case "box", "bottom_center", "top_center", "center": // 枠全体 / 足元 / 頭 / 体の中心
			cols["anchor"] = *p.Anchor
		default:
			return nil, errInvalid("anchor は box / bottom_center / top_center / center")
		}
	}
	if p.SampleFPS != nil {
		if *p.SampleFPS < 0.5 || *p.SampleFPS > 10 {
			return nil, errInvalid("認識の頻度は 0.5〜10 枚/秒で指定する")
		}
		cols["sample_fps"] = *p.SampleFPS
	}
	if len(cols) > 0 {
		if err := s.repo.UpdateCamera(id, cols); err != nil {
			return nil, err
		}
	}
	return s.mustGet(id)
}

// SetRecognizing は、認識の開始・停止（管理画面の指示）。スマホは、この状態に従って映像を送る。
func (s *CameraService) SetRecognizing(id string, on bool) error {
	cam, err := s.mustGet(id)
	if err != nil {
		return err
	}
	if cam.Source != "db" {
		return errConflict("yaml で固定したカメラには、スマホがない")
	}
	return s.repo.UpdateCamera(id, map[string]any{"recognizing": on})
}

// SetCameraSettings は、スマホのカメラの設定を保存する（管理画面の指示。スマホが従う）。
// 受け付ける項目：res（"1280x960" の形）、zoom（数）、device_id（カメラの ID）。他の項目は捨てる。
func (s *CameraService) SetCameraSettings(id string, in map[string]any) (json.RawMessage, error) {
	cam, err := s.mustGet(id)
	if err != nil {
		return nil, err
	}
	if cam.Source != "db" {
		return nil, errConflict("yaml で固定したカメラには、スマホがない")
	}
	// 前の設定に、重ねる（1 項目だけ送っても、他の項目は、残る）
	out := map[string]any{}
	if len(cam.CameraSettings) > 2 {
		_ = json.Unmarshal(cam.CameraSettings, &out)
	}
	if v, ok := in["res"].(string); ok && v != "" {
		var w, h int
		if n, _ := fmt.Sscanf(v, "%dx%d", &w, &h); n != 2 || w < 160 || h < 120 || w > 4096 || h > 4096 {
			return nil, errInvalid("解像度は 1280x960 の形で、160x120〜4096x4096")
		}
		out["res"] = v
	}
	if v, ok := in["zoom"].(float64); ok {
		if v < 0.1 || v > 20 {
			return nil, errInvalid("ズームは 0.1〜20")
		}
		out["zoom"] = v
	}
	if v, ok := in["bitrate"].(float64); ok { // kbps。0 は、自動
		if v < 0 || (v > 0 && (v < 100 || v > 8000)) {
			return nil, errInvalid("ビットレートは 100〜8000 kbps（0 で自動）")
		}
		out["bitrate"] = int(v)
	}
	if v, ok := in["device_id"].(string); ok && v != "" {
		if len(v) > 200 {
			return nil, errInvalid("カメラの ID が長すぎる")
		}
		out["device_id"] = v
	}
	b, _ := json.Marshal(out)
	if err := s.repo.UpdateCamera(id, map[string]any{"camera_settings": models.JSON(b)}); err != nil {
		return nil, err
	}
	return b, nil
}

// Delete は、登録を解除する（送信中は不可）。通過の記録は残る。
func (s *CameraService) Delete(id string, streaming bool) error {
	cam, err := s.mustGet(id)
	if err != nil {
		return err
	}
	if cam.Source != "db" {
		return errConflict("yaml で固定したカメラは、ここでは削除できない")
	}
	if streaming {
		return errConflict("送信中は削除できない。先に停止する")
	}
	return s.repo.DeleteCamera(id)
}

// ---------------------------------------------------------------------------
// 入力の検査
// ---------------------------------------------------------------------------

func round4(v float64) float64 { return math.Round(v*10000) / 10000 }

// validateLine は、カウントラインの座標が「2 点・各座標 0〜1・短すぎない」ことを確かめる。
func validateLine(line [][]float64) ([][]float64, error) {
	if len(line) != 2 {
		return nil, errInvalid("line は [[x1,y1],[x2,y2]]（各 0〜1）で指定する")
	}
	for _, p := range line {
		if len(p) != 2 || p[0] < 0 || p[0] > 1 || p[1] < 0 || p[1] > 1 {
			return nil, errInvalid("line は [[x1,y1],[x2,y2]]（各 0〜1）で指定する")
		}
	}
	if math.Hypot(line[1][0]-line[0][0], line[1][1]-line[0][1]) < 0.05 {
		return nil, errInvalid("線が短すぎる")
	}
	return [][]float64{{round4(line[0][0]), round4(line[0][1])}, {round4(line[1][0]), round4(line[1][1])}}, nil
}

// validateLines は、線のリストを検査して整える。1 本以上、12 本まで。名前は重複できない
// （通過の記録に線の名前を使うので、同じ名前だと、どちらの線か分からなくなる）。
func validateLines(lines []models.Line) ([]models.Line, error) {
	if len(lines) < 1 {
		return nil, errInvalid("線は 1 本以上必要")
	}
	if len(lines) > 12 {
		return nil, errInvalid("線は 12 本まで")
	}
	out := make([]models.Line, 0, len(lines))
	names := map[string]bool{}
	for i, l := range lines {
		if len(l.ID) == 0 || len(l.ID) > 24 {
			return nil, errInvalid("線の id は 1〜24 文字")
		}
		pts, err := validateLine(l.Line)
		if err != nil {
			return nil, err
		}
		name := strings.TrimSpace(l.Name)
		if name == "" {
			name = fmt.Sprintf("線%d", i+1)
		}
		if len([]rune(name)) > 30 {
			return nil, errInvalid("線の名前は 30 文字まで")
		}
		if names[name] {
			return nil, errInvalid("線の名前が重複している: " + name)
		}
		names[name] = true
		out = append(out, models.Line{ID: l.ID, Name: name, Line: pts})
	}
	return out, nil
}
