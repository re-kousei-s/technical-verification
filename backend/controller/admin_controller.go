package controller

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/gorilla/websocket"
	"github.com/labstack/echo/v4"

	"humandetect/models"
	"humandetect/repository"
	"humandetect/services"
	"humandetect/web"
)

// AdminController は、管理画面向けの入口。
//
//	一覧（/api/overview）、人数の補正・リセット、検出枠つきの画像、ライブ表示（H.264 の中継）
type AdminController struct {
	overview *services.OverviewService
	floors   *services.FloorService
	streams  *services.StreamService
	cameras  *services.CameraService
	db       *repository.DBRepository
	queue    *repository.QueueRepository
}

func NewAdminController(overview *services.OverviewService, floors *services.FloorService,
	streams *services.StreamService, cameras *services.CameraService, db *repository.DBRepository,
	queue *repository.QueueRepository) *AdminController {
	return &AdminController{overview, floors, streams, cameras, db, queue}
}

// Register は、ルーティングを登録する。
func (a *AdminController) Register(e *echo.Echo) {
	// 管理画面（React）。ページの切り替えは # 以降なので、入口は / だけでよい
	adminFiles := http.FileServer(http.FS(web.AdminFS()))
	serveAdmin := echo.WrapHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" { // 画面の本体は、いつも最新を読ませる（assets/ はファイル名にハッシュが付くので、そのままでよい）
			w.Header().Set("Cache-Control", "no-store")
		}
		adminFiles.ServeHTTP(w, r)
	}))
	e.GET("/", serveAdmin)
	e.GET("/assets/*", serveAdmin)
	e.GET("/healthz", func(c echo.Context) error { return c.JSON(200, map[string]bool{"ok": true}) })

	e.GET("/api/overview", a.getOverview)
	e.GET("/api/camera/:id/frame.jpg", a.frame)
	e.GET("/api/camera/:id/result", func(c echo.Context) error { return jsonResult(c, a.queue) })
	e.GET("/api/crossings", a.crossings)

	e.POST("/api/floors/:floor/count", a.setFloorCount)
	e.POST("/api/floors/reset", a.resetFloors)
	e.POST("/api/history/reset", a.resetHistory)
	e.POST("/api/reset-all", a.resetAll)

	e.PUT("/api/camera/:id/lines", a.putLines)                    // 管理画面の線の編集
	e.PUT("/api/camera/:id/camera-settings", a.setCameraSettings) // スマホのカメラの設定（解像度・ズーム・カメラ）
	e.POST("/api/cameras", a.addCamera)                           // 端末の追加（スマホからは、追加できない。管理画面だけ）
	e.DELETE("/api/camera/:id", a.deleteCamera)                   // 端末の削除（スマホが接続中でも、切って削除する）
	e.POST("/api/recognize/all", a.setRecognizeAll)               // 全端末の認識の一括開始・停止
	e.POST("/api/camera/:id/recognize", a.setRecognize)           // 認識の開始・停止（スマホは、この指示に従う）
	e.GET("/api/live/:id/info", a.liveInfo)
	e.GET("/api/live/:id", a.liveWS) // H.264 の中継（WebSocket）
}

// getOverview は、一覧に出す情報すべて。管理画面が 2 秒ごとに読む。
func (a *AdminController) getOverview(c echo.Context) error {
	o, err := a.overview.Build(c.Request().Context())
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, o)
}

// frame は、worker が描いた「検出枠つきの最新画像」。
func (a *AdminController) frame(c echo.Context) error {
	img := a.queue.Annotated(c.Request().Context(), c.Param("id"))
	if img == nil {
		return fail(c, &services.Error{Code: 404, Message: "まだ画像がない"})
	}
	c.Response().Header().Set("Cache-Control", "no-store")
	return c.Blob(200, "image/jpeg", img)
}

// crossings は、通過の履歴。?limit=100&camera_id=...
func (a *AdminController) crossings(c echo.Context) error {
	limit, _ := strconv.Atoi(c.QueryParam("limit"))
	if limit <= 0 || limit > 1000 {
		limit = 100
	}
	rows, err := a.db.RecentCrossings(limit, c.QueryParam("camera_id"))
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, rows)
}

// ---------------------------------------------------------------------------
// 補正・リセット
// ---------------------------------------------------------------------------

// setFloorCount は、スタッフによる人数の補正。 POST /api/floors/2/count {"count": 12}
func (a *AdminController) setFloorCount(c echo.Context) error {
	floor, err := strconv.Atoi(c.Param("floor"))
	if err != nil {
		return fail(c, &services.Error{Code: 422, Message: "フロアは整数で指定する"})
	}
	var body struct {
		Count int `json:"count"`
	}
	if err := c.Bind(&body); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "count を指定する"})
	}
	if err := a.floors.SetCount(floor, body.Count); err != nil {
		return fail(c, err)
	}
	return c.JSON(200, map[string]int{"floor": floor, "count": body.Count})
}

// resetFloors は、全フロアの人数を 0 に戻す（閉場）。
func (a *AdminController) resetFloors(c echo.Context) error {
	n, err := a.floors.ResetFloors()
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, map[string]int64{"reset": n})
}

// resetHistory は、IN/OUT の履歴を消す。 {} で全部、{"floor": 2}、{"camera_id": "..."}。
func (a *AdminController) resetHistory(c echo.Context) error {
	var body struct {
		CameraID string `json:"camera_id"`
		Floor    *int   `json:"floor"`
	}
	_ = c.Bind(&body)
	n, err := a.floors.ResetHistory(body.CameraID, body.Floor)
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, map[string]int64{"deleted_crossings": n})
}

// resetAll は、全部リセット。
func (a *AdminController) resetAll(c echo.Context) error {
	res, err := a.floors.ResetAll()
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, res)
}

// ---------------------------------------------------------------------------
// ライブ表示
// ---------------------------------------------------------------------------

// liveInfo は、ライブ表示の画面に出す状況。受信の状況に加えて、映像に重ねる「線」と IN/OUT を返す。
func (a *AdminController) liveInfo(c echo.Context) error {
	id := c.Param("id")
	info, err := a.streams.LiveInfo(id)
	if err != nil {
		return fail(c, err)
	}
	lines := []models.Line{}
	if cam, _ := a.cameras.Get(id); cam != nil {
		lines = cam.Lines
	}
	state, _ := a.db.CameraState(id)
	counts, _ := a.db.LineCounts(id)
	if counts == nil {
		counts = map[string]repository.LineCount{}
	}
	return c.JSON(200, struct {
		services.LiveInfo
		Lines      []models.Line                   `json:"lines"`       // 数える線（映像に重ねる）
		In         int                             `json:"in"`          // この端末の累計 IN
		Out        int                             `json:"out"`         // この端末の累計 OUT
		LineCounts map[string]repository.LineCount `json:"line_counts"` // 線ごとの IN/OUT
	}{info, lines, state.InCount, state.OutCount, counts})
}

// liveWS は、スマホから届いた H.264 を、デコードせずにそのまま管理画面へ流す。
// バイナリメッセージ 1 つ = H.264 の 1 フレームぶん（Annex B）。デコードは管理画面のブラウザが行う。
// 見ている間だけ、スマホに高い fps を頼む（services が視聴者の数を見て判断する）。
func (a *AdminController) liveWS(c echo.Context) error {
	conn := upgrade(c)
	if conn == nil {
		return nil
	}
	defer conn.Conn.Close()

	id := c.Param("id")
	thumb := c.QueryParam("thumb") == "1" // 一覧の小さな表示（低い fps で足りる。時間の上限もない）
	viewer, cancel, err := a.streams.Subscribe(id, thumb)
	if err != nil {
		code, reason := closeCodeFor(err)
		conn.closeWith(code, reason)
		return nil
	}
	defer cancel()
	// 視聴の開始と終了を記録する（「見ていないのに、高い fps のまま」のとき、残っている接続を、探せるように）
	start := time.Now()
	log.Printf("映像の視聴を開始 %s thumb=%v 接続元=%s", id, thumb, c.RealIP())
	defer func() {
		log.Printf("映像の視聴を終了 %s thumb=%v 接続元=%s（%.0f 秒）", id, thumb, c.RealIP(), time.Since(start).Seconds())
	}()

	// 管理画面側が閉じたかを知るため、読み続ける（届くメッセージは使わない）
	closed := make(chan struct{})
	go func() {
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				close(closed)
				return
			}
		}
	}()

	var limitC <-chan time.Time // リアルタイム表示だけ、閉じ忘れ対策の上限を付ける
	if !thumb {
		limit := time.NewTimer(a.streams.MaxLiveSeconds())
		defer limit.Stop()
		limitC = limit.C
	}
	// 認識結果（検出枠など）は、映像と同じ接続で、変わったときだけ（約 0.25 秒ごとに確かめて）テキストで流す。
	// 見ている間だけ読むので、見ていないときは、Redis を読みに行かない。
	results := time.NewTicker(250 * time.Millisecond)
	defer results.Stop()
	var lastResult string
	for {
		select {
		case <-results.C:
			if raw := a.queue.Result(context.Background(), id); raw != nil && string(raw) != lastResult {
				lastResult = string(raw)
				if err := conn.WriteText(lastResult); err != nil {
					return nil
				}
			}
		case chunk := <-viewer.C:
			if err := conn.WriteBinary(chunk); err != nil {
				return nil
			}
			a.streams.AddTx(id, len(chunk))
		case <-closed:
			return nil
		case <-limitC:
			conn.closeWith(websocket.CloseNormalClosure, "time limit")
			return nil
		}
	}
}

// jsonResult は、worker が出した最新の認識結果をそのまま返す。無ければ「古い」扱いの空の結果。
func jsonResult(c echo.Context, q *repository.QueueRepository) error {
	c.Response().Header().Set("Cache-Control", "no-store")
	if raw := q.Result(c.Request().Context(), c.Param("id")); raw != nil {
		return c.JSONBlob(200, raw)
	}
	return c.JSON(200, map[string]any{"boxes": []any{}, "events": []any{}, "stale": true})
}

// putLines は、管理画面で編集した線を保存する（端末の設定の lines だけを更新）。
// yaml で固定したカメラは、services 側で断られる。
func (a *AdminController) putLines(c echo.Context) error {
	var lines []models.Line
	if err := c.Bind(&lines); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "JSON を読めない"})
	}
	cam, err := a.cameras.Update(c.Param("id"), services.CameraPatch{Lines: &lines})
	if err != nil {
		return fail(c, err)
	}
	if b, err := json.Marshal(cam.Lines); err == nil {
		a.streams.SetLines(c.Param("id"), b) // 接続中のスマホにも、同じ線を伝える
	}
	return c.JSON(200, cam)
}

// setRecognize は、認識の開始・停止。 POST /api/camera/F2-789E/recognize {"on": true}
// 状態を DB に残し、スマホの待機用の接続へ伝える（スマホは、「認識中」の間だけ映像を送る）。
func (a *AdminController) setRecognize(c echo.Context) error {
	var body struct {
		On bool `json:"on"`
	}
	if err := c.Bind(&body); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "on を指定する"})
	}
	id := c.Param("id")
	if err := a.cameras.SetRecognizing(id, body.On); err != nil {
		return fail(c, err)
	}
	a.streams.SetRecognize(id, body.On)
	return c.JSON(200, map[string]any{"id": id, "recognizing": body.On})
}

// setCameraSettings は、スマホのカメラの設定。 PUT /api/camera/F2-789E/camera-settings {"res":"1280x960","zoom":1.5,"device_id":"…"}
func (a *AdminController) setCameraSettings(c echo.Context) error {
	var in map[string]any
	if err := c.Bind(&in); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "JSON を読めない"})
	}
	id := c.Param("id")
	raw, err := a.cameras.SetCameraSettings(id, in)
	if err != nil {
		return fail(c, err)
	}
	a.streams.SetCameraSettings(id, raw)
	return c.JSONBlob(200, raw)
}

// setRecognizeAll は、スマホのある全端末の認識を、まとめて開始・停止する。 POST /api/recognize/all {"on": true}
func (a *AdminController) setRecognizeAll(c echo.Context) error {
	var body struct {
		On bool `json:"on"`
	}
	if err := c.Bind(&body); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "on を指定する"})
	}
	all, err := a.cameras.All()
	if err != nil {
		return fail(c, err)
	}
	n := 0
	for _, cam := range all {
		if cam.Source != "db" {
			continue // yaml の固定端末には、スマホがない
		}
		if err := a.cameras.SetRecognizing(cam.ID, body.On); err != nil {
			return fail(c, err)
		}
		a.streams.SetRecognize(cam.ID, body.On)
		n++
	}
	return c.JSON(200, map[string]any{"on": body.On, "cameras": n})
}

// deleteCamera は、端末の登録を削除する。通過の記録（crossings）は、残る。
// スマホが接続中なら、切る（スマホは、登録がないと知って、つなぎ直さない）。yaml で固定した端末は、削除できない。
func (a *AdminController) deleteCamera(c echo.Context) error {
	id := c.Param("id")
	if err := a.cameras.Delete(id, false); err != nil {
		return fail(c, err)
	}
	a.streams.Forget(id)
	a.queue.ReleasePartition(c.Request().Context(), id) // キューの割り当てを、空ける
	return c.JSON(200, map[string]bool{"ok": true})
}

// addCamera は、端末を追加する。 POST /api/cameras {"floor": 2, "name": "階段A"}
// 端末の追加は、管理画面だけができる。スマホは、追加された端末の一覧から、選ぶだけ。
func (a *AdminController) addCamera(c echo.Context) error {
	var body struct {
		Floor int    `json:"floor"`
		Name  string `json:"name"`
	}
	if err := c.Bind(&body); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "floor と name を指定する"})
	}
	cam, err := a.cameras.Register(body.Floor, body.Name)
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, cam)
}
