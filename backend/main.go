// 人検出バックエンド。
//
// スマホから H.264 の映像を受け取り、
//   - 認識用：ffmpeg でデコードして 5fps に間引き、Redis のキューに積む（Python の worker が認識して DB を更新する）
//   - 表示用：受け取った H.264 を、そのまま管理画面へ中継する（デコードは管理画面のブラウザが行う）
//
// ほかに、端末の登録・設定の API と、管理画面の一覧の API を持つ。
//
// 構成（依存の向き）： controller → services → repository → models
package main

import (
	"log"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/redis/go-redis/v9"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"

	"humandetect/config"
	"humandetect/controller"
	"humandetect/repository"
	"humandetect/services"
)

func main() {
	env := config.LoadEnv()

	// --- 接続（DB が起動中なら、つながるまで待つ） ---
	db := connectDB(env.DatabaseURL)
	rdb := redis.NewClient(mustParseRedis(env.RedisURL))

	// --- 組み立て：下の層から順に作って、上の層に渡す ---
	dbRepo := repository.NewDBRepository(db)
	queueRepo := repository.NewQueueRepository(rdb, env.Partitions)

	cameras := services.NewCameraService(dbRepo, env.CamerasPath)
	hub := services.NewLiveHub()
	streams := services.NewStreamService(env, cameras, queueRepo, hub)
	floors := services.NewFloorService(dbRepo, cameras)
	overview := services.NewOverviewService(dbRepo, queueRepo, cameras, streams)

	// --- 2 つのサーバー：スマホ向け（:8000）と、管理画面向け（:8080） ---
	deviceServer := newEcho()
	controller.NewDeviceController(cameras, streams, floors, dbRepo, queueRepo).Register(deviceServer)

	adminServer := newEcho()
	controller.NewAdminController(overview, floors, streams, cameras, dbRepo, queueRepo).Register(adminServer)

	go func() { log.Fatal(adminServer.Start(env.AdminAddr)) }()
	log.Printf("起動: スマホ向け %s / 管理画面 %s", env.DeviceAddr, env.AdminAddr)
	log.Fatal(deviceServer.Start(env.DeviceAddr))
}

// newEcho は、共通の設定をした echo を作る。
func newEcho() *echo.Echo {
	e := echo.New()
	e.HideBanner, e.HidePort = true, true
	e.Use(middleware.Recover()) // 処理中の panic で、サーバー全体が落ちないようにする
	return e
}

// connectDB は、PostgreSQL につなぐ。つながるまで 2 秒おきに再試行する。
func connectDB(dsn string) *gorm.DB {
	for {
		db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Warn)})
		if err == nil {
			if sqlDB, err := db.DB(); err == nil && sqlDB.Ping() == nil {
				return db
			}
		}
		log.Printf("DB に接続できない（再試行）: %v", err)
		time.Sleep(2 * time.Second)
	}
}

func mustParseRedis(url string) *redis.Options {
	opt, err := redis.ParseURL(url)
	if err != nil {
		log.Fatalf("REDIS_URL を読めない: %v", err)
	}
	return opt
}
