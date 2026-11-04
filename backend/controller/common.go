// Package controller は、HTTP と WebSocket の入口。
// リクエストを読み取り、services を呼び、結果を JSON で返すだけにして、業務ルールは書かない。
package controller

import (
	"errors"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/labstack/echo/v4"

	"humandetect/services"
)

// fail は、エラーを JSON で返す。形は {"detail": "説明"}（画面側がこの形を読む）。
// services.Error ならその Code を、それ以外は 500 を使う。
func fail(c echo.Context, err error) error {
	var e *services.Error
	if errors.As(err, &e) {
		return c.JSON(e.Code, map[string]string{"detail": e.Message})
	}
	c.Logger().Error(err)
	return c.JSON(http.StatusInternalServerError, map[string]string{"detail": err.Error()})
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

// upgrader は、HTTP を WebSocket に切り替える。Origin は検査しない（検証用。LAN の中だけで使う前提）。
var upgrader = websocket.Upgrader{
	CheckOrigin:     func(r *http.Request) bool { return true },
	ReadBufferSize:  64 << 10,
	WriteBufferSize: 64 << 10,
}

// WebSocket のクローズコード（スマホ・管理画面の JavaScript が、この数字を見て動きを変える）
const (
	closeNotFound = 4404 // 登録されていない端末
	closeBusy     = 4409 // その端末は、すでに送信中
	closeReplaced = 4410 // 同じ端末の新しいページが開いたので、古い接続を閉じた
)

// wsConn は、gorilla の WebSocket を services.Conn として使えるようにする包み。
// gorilla は「書く処理は同時に 1 つだけ」という決まりなので、書くときは鍵をかける。
type wsConn struct {
	*websocket.Conn
	mu sync.Mutex
}

func (w *wsConn) WriteText(s string) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.WriteMessage(websocket.TextMessage, []byte(s))
}

func (w *wsConn) WriteBinary(b []byte) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.WriteMessage(websocket.BinaryMessage, b)
}

// closeWith は、クローズコードと理由を付けて接続を閉じる。
func (w *wsConn) closeWith(code int, reason string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	_ = w.WriteControl(websocket.CloseMessage, websocket.FormatCloseMessage(code, reason), time.Now().Add(time.Second))
	_ = w.Conn.Close()
}

// Close は、services が「新しいページに置き換えられた」ときに呼ぶ。
func (w *wsConn) Close() error {
	w.closeWith(closeReplaced, "replaced by a newer page")
	return nil
}

// Kick は、端末が削除されたとき、services が呼ぶ。スマホは、4404（登録がない）を見て、つなぎ直さない。
func (w *wsConn) Kick() error {
	w.closeWith(closeNotFound, "camera deleted")
	return nil
}

// closeCodeFor は、エラーを WebSocket のクローズコードに直す。
func closeCodeFor(err error) (int, string) {
	var e *services.Error
	if errors.As(err, &e) {
		switch e.Code {
		case http.StatusNotFound:
			return closeNotFound, e.Message
		case http.StatusConflict:
			return closeBusy, e.Message
		}
	}
	return websocket.CloseInternalServerErr, "internal error"
}

// upgrade は、WebSocket に切り替える。失敗したら nil（エラー応答は gorilla が返す）。
func upgrade(c echo.Context) *wsConn {
	conn, err := upgrader.Upgrade(c.Response(), c.Request(), nil)
	if err != nil {
		return nil
	}
	conn.SetReadLimit(16 << 20) // 1 チャンクが大きなキーフレームでも受けられるように
	return &wsConn{Conn: conn}
}
