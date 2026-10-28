package services

import "net/http"

// Error は、利用者に返すエラー。Code は HTTP のステータス、Message は画面に出す日本語の説明。
type Error struct {
	Code    int
	Message string
}

func (e *Error) Error() string { return e.Message }

func errInvalid(msg string) error  { return &Error{http.StatusUnprocessableEntity, msg} } // 入力が不正
func errNotFound(msg string) error { return &Error{http.StatusNotFound, msg} }            // 無い
func errConflict(msg string) error { return &Error{http.StatusConflict, msg} }            // いまは操作できない
