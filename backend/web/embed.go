// Package web は、ブラウザに配る画面をバイナリに埋め込む。
package web

import (
	"embed"
	"io/fs"
)

// SenderHTML は、スマホ用の送信ページ（カメラの映像を H.264 にして送る）。
//
//go:embed sender.html
var SenderHTML []byte

// adminDist は、管理画面（React）をビルドした結果。
// Docker のビルド中に backend/admin を npm run build して、ここ（admin_dist）に入れる。
//
//go:embed all:admin_dist
var adminDist embed.FS

// AdminFS は、管理画面のファイル（index.html と assets/）を、ルートとして見せる。
func AdminFS() fs.FS {
	sub, err := fs.Sub(adminDist, "admin_dist")
	if err != nil {
		panic(err) // 埋め込みの設定ミス（起動時に気づける）
	}
	return sub
}
