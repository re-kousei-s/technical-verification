package controller

import (
	"net/http"
	"strconv"

	"github.com/labstack/echo/v4"

	"humandetect/models"
	"humandetect/repository"
	"humandetect/services"
	"humandetect/web"
)

// DeviceController は、スマホ（送信ページ）向けの入口。
//
//	送信ページの配信、端末の登録・設定、映像の受信（WebSocket）、待機用の接続（WebSocket）
type DeviceController struct {
	cameras *services.CameraService
	streams *services.StreamService
	floors  *services.FloorService
	db      *repository.DBRepository
	queue   *repository.QueueRepository
}

func NewDeviceController(cameras *services.CameraService, streams *services.StreamService,
	floors *services.FloorService, db *repository.DBRepository, queue *repository.QueueRepository) *DeviceController {
	return &DeviceController{cameras, streams, floors, db, queue}
}

// Register は、ルーティング（URL と処理の対応）を登録する。
func (d *DeviceController) Register(e *echo.Echo) {
	e.GET("/", d.senderPage)
	e.GET("/sender", d.senderPage)
	e.GET("/healthz", func(c echo.Context) error { return c.JSON(200, map[string]bool{"ok": true}) })

	e.GET("/api/floors", d.listFloors)
	e.POST("/api/register", d.register)
	e.GET("/api/cameras/:id", d.getCamera)
	e.PATCH("/api/cameras/:id", d.patchCamera)
	e.DELETE("/api/cameras/:id", d.deleteCamera)
	e.GET("/api/cameras/:id/result", d.result)
	e.POST("/api/cameras/:id/reset", d.resetCamera)
	e.POST("/api/reset-all", d.resetAll)

	e.GET("/ws/:id", d.streamWS)   // 映像（H.264）
	e.GET("/ctl/:id", d.controlWS) // 待機用
}

// senderPage は、スマホ用の送信ページ。
func (d *DeviceController) senderPage(c echo.Context) error {
	c.Response().Header().Set("Cache-Control", "no-store")
	return c.HTMLBlob(http.StatusOK, web.SenderHTML)
}

// ---------------------------------------------------------------------------
// 端末の登録・設定
// ---------------------------------------------------------------------------

// deviceView は、端末の設定に「いま送信中か」を足したもの。
type deviceView struct {
	models.CameraConfig
	Connected bool `json:"connected"`
}

// listFloors は、フロアごとの登録端末の一覧。
func (d *DeviceController) listFloors(c echo.Context) error {
	cams, err := d.cameras.All()
	if err != nil {
		return fail(c, err)
	}
	type floor struct {
		Floor   int          `json:"floor"`
		Devices []deviceView `json:"devices"`
	}
	out := []floor{}
	for _, cam := range cams { // cams はフロア順に並んでいる
		if len(out) == 0 || out[len(out)-1].Floor != cam.Floor {
			out = append(out, floor{Floor: cam.Floor, Devices: []deviceView{}})
		}
		last := &out[len(out)-1]
		last.Devices = append(last.Devices, deviceView{cam, d.streams.IsStreaming(cam.ID)})
	}
	return c.JSON(200, out)
}

// register は、端末を登録する。{"floor": 2, "name": "階段A"}
func (d *DeviceController) register(c echo.Context) error {
	var body struct {
		Floor int    `json:"floor"`
		Name  string `json:"name"`
	}
	if err := c.Bind(&body); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "floor と name を JSON で指定する"})
	}
	cam, err := d.cameras.Register(body.Floor, body.Name)
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, cam)
}

// getCamera は、端末の設定（線）と、受信・カウントの状況。送信ページが 2 秒ごとに読む。
func (d *DeviceController) getCamera(c echo.Context) error {
	cam, err := d.cameras.Get(c.Param("id"))
	if err != nil {
		return fail(c, err)
	}
	if cam == nil {
		return fail(c, &services.Error{Code: 404, Message: "登録されていない端末"})
	}
	rt := d.streams.Snapshot(cam.ID)
	state, _ := d.db.CameraState(cam.ID)
	est, _ := d.floors.Estimate(cam.Floor)
	lineCounts, _ := d.db.LineCounts(cam.ID)
	if lineCounts == nil {
		lineCounts = map[string]repository.LineCount{}
	}
	type server struct {
		Decoded      int64 `json:"decoded"`
		Enqueued     int64 `json:"enqueued"`
		Dropped      int64 `json:"dropped"`
		DecodeErrors int64 `json:"decode_errors"`
	}
	return c.JSON(200, struct {
		models.CameraConfig
		Connected     bool                            `json:"connected"`
		Server        server                          `json:"server"`
		In            int                             `json:"in"`
		Out           int                             `json:"out"`
		FloorEstimate services.Estimate               `json:"floor_estimate"`
		LineCounts    map[string]repository.LineCount `json:"line_counts"`
	}{*cam, rt.Active, server{rt.Decoded, rt.Enqueued, rt.Dropped, rt.DecodeErrors},
		state.InCount, state.OutCount, est, lineCounts})
}

// patchCamera は、線・認識の頻度の変更。
func (d *DeviceController) patchCamera(c echo.Context) error {
	var patch services.CameraPatch
	if err := c.Bind(&patch); err != nil {
		return fail(c, &services.Error{Code: 422, Message: "JSON を読めない"})
	}
	cam, err := d.cameras.Update(c.Param("id"), patch)
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, cam)
}

// deleteCamera は、登録の解除。
func (d *DeviceController) deleteCamera(c echo.Context) error {
	if err := d.cameras.Delete(c.Param("id"), d.streams.IsStreaming(c.Param("id"))); err != nil {
		return fail(c, err)
	}
	return c.JSON(200, map[string]bool{"ok": true})
}

// result は、worker が出した最新の認識結果（検出枠など）。送信ページが映像に重ねる。
func (d *DeviceController) result(c echo.Context) error {
	return jsonResult(c, d.queue)
}

// resetCamera は、この端末の IN/OUT の履歴を消す。
func (d *DeviceController) resetCamera(c echo.Context) error {
	id := c.Param("id")
	if cam, err := d.cameras.Get(id); err != nil || cam == nil {
		return fail(c, &services.Error{Code: 404, Message: "登録されていない端末"})
	}
	n, err := d.floors.ResetHistory(id, nil)
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, map[string]int64{"deleted_crossings": n})
}

// resetAll は、全部リセット（全端末の履歴と、全フロアの人数）。
func (d *DeviceController) resetAll(c echo.Context) error {
	res, err := d.floors.ResetAll()
	if err != nil {
		return fail(c, err)
	}
	return c.JSON(200, res)
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

// streamWS は、映像の受信。 /ws/:id?mode=send|live&ts_header=0|1
//
//	バイナリメッセージ = H.264（Annex B）の 1 フレームぶん。
func (d *DeviceController) streamWS(c echo.Context) error {
	conn := upgrade(c)
	if conn == nil {
		return nil
	}
	mode := services.ModeSend
	if c.QueryParam("mode") == services.ModeLive {
		mode = services.ModeLive
	}
	tsHeader, _ := strconv.Atoi(c.QueryParam("ts_header"))

	if err := d.streams.RunStream(c.Param("id"), mode, tsHeader == 1, conn); err != nil {
		code, reason := closeCodeFor(err)
		conn.closeWith(code, reason)
		return nil
	}
	_ = conn.Conn.Close()
	return nil
}

// controlWS は、スマホの送信ページの待機用の接続。映像は流れず、サーバーからの指示が流れる。
func (d *DeviceController) controlWS(c echo.Context) error {
	conn := upgrade(c)
	if conn == nil {
		return nil
	}
	if err := d.streams.RunControl(c.Param("id"), conn); err != nil {
		code, reason := closeCodeFor(err)
		conn.closeWith(code, reason)
		return nil
	}
	_ = conn.Conn.Close()
	return nil
}
