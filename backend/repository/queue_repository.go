package repository

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// consumerGroup は、Python の worker が使う Redis Streams のコンシューマーグループ名（worker 側と合わせる）。
const consumerGroup = "recognizers"

// QueueRepository は、Redis の読み書き。
//   - frames:p{n}   キュー（Redis Streams）。バックエンドが積み、Python の worker が取り出す
//   - worker:{名前} worker のハートビート
//   - annotated:{id} / result:{id}  worker が出す、検出枠つきの画像と最新の認識結果
type QueueRepository struct {
	rdb        *redis.Client
	partitions int
}

func NewQueueRepository(rdb *redis.Client, partitions int) *QueueRepository {
	return &QueueRepository{rdb: rdb, partitions: partitions}
}

func (q *QueueRepository) Ping(ctx context.Context) error { return q.rdb.Ping(ctx).Err() }

// PartitionOf は、端末をどのキュー（= どの worker）に振るかを決める。
// 同じ端末のフレームは必ず同じ worker に届くようにする（追跡の状態を持つため）。
// Python 側（worker）と同じ式：md5(camera_id) を整数と見て、分割数で割った余り。
func (q *QueueRepository) PartitionOf(cameraID string) int {
	return partitionOf(cameraID, q.partitions)
}

func streamName(partition int) string { return "frames:p" + strconv.Itoa(partition) }

// Length は、そのキューに溜まっているフレームの数（未処理 + 処理中）。
func (q *QueueRepository) Length(ctx context.Context, partition int) (int64, error) {
	return q.rdb.XLen(ctx, streamName(partition)).Result()
}

// Enqueue は、間引いたフレーム（JPEG）をキューに積む。worker が読むフィールド名はここで決まる。
func (q *QueueRepository) Enqueue(ctx context.Context, cameraID string, tsMs int64, w, h int, jpeg []byte) error {
	return q.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: streamName(q.PartitionOf(cameraID)),
		Values: map[string]any{
			"camera_id": cameraID,
			"ts_ms":     tsMs,
			"w":         w,
			"h":         h,
			"enq_ms":    time.Now().UnixMilli(),
			"jpeg":      jpeg,
		},
	}).Err()
}

// QueueInfo は、管理画面に出すキュー 1 本の状態。
type QueueInfo struct {
	Partition int    `json:"partition"`
	Stream    string `json:"stream"`
	Length    int64  `json:"length"`  // 待ち
	Pending   int64  `json:"pending"` // 処理中（未 ACK）
	Lag       *int64 `json:"lag"`     // 未配信
}

// Queues は、全キューの状態。
func (q *QueueRepository) Queues(ctx context.Context) []QueueInfo {
	out := make([]QueueInfo, 0, q.partitions)
	for p := 0; p < q.partitions; p++ {
		info := QueueInfo{Partition: p, Stream: streamName(p)}
		info.Length, _ = q.rdb.XLen(ctx, info.Stream).Result()
		if groups, err := q.rdb.XInfoGroups(ctx, info.Stream).Result(); err == nil {
			for _, g := range groups {
				if g.Name == consumerGroup {
					info.Pending = g.Pending
					lag := g.Lag
					info.Lag = &lag
				}
			}
		}
		out = append(out, info)
	}
	return out
}

// WorkerInfo は、worker のハートビート 1 件。
type WorkerInfo struct {
	Name       string `json:"name"`
	Detector   string `json:"detector"`
	Partitions string `json:"partitions"`
	Processed  string `json:"processed"`
	Errors     string `json:"errors"`
	InferMs    string `json:"infer_ms_avg"`
	LagMs      string `json:"lag_ms_avg"`
	AgeMs      int64  `json:"age_ms"`
	Alive      bool   `json:"alive"`
}

// Workers は、動いている worker の一覧。ハートビートが staleAfter より古ければ止まっているとみなす。
func (q *QueueRepository) Workers(ctx context.Context, staleAfter time.Duration) []WorkerInfo {
	var out []WorkerInfo
	iter := q.rdb.Scan(ctx, 0, "worker:*", 100).Iterator()
	for iter.Next(ctx) {
		key := iter.Val()
		h, err := q.rdb.HGetAll(ctx, key).Result()
		if err != nil || len(h) == 0 {
			continue
		}
		last, _ := strconv.ParseInt(h["last_seen_ms"], 10, 64)
		age := time.Now().UnixMilli() - last
		out = append(out, WorkerInfo{
			Name: strings.TrimPrefix(key, "worker:"), Detector: h["detector"], Partitions: h["partitions"],
			Processed: h["processed"], Errors: h["errors"], InferMs: h["infer_ms_avg"], LagMs: h["lag_ms_avg"],
			AgeMs: age, Alive: age < staleAfter.Milliseconds(),
		})
	}
	return out
}

// Annotated は、worker が描いた「検出枠つきの最新画像」（JPEG）。無ければ nil。
func (q *QueueRepository) Annotated(ctx context.Context, cameraID string) []byte {
	b, err := q.rdb.Get(ctx, "annotated:"+cameraID).Bytes()
	if err != nil {
		return nil
	}
	return b
}

// HasAnnotated は、検出枠つきの画像があるか。
func (q *QueueRepository) HasAnnotated(ctx context.Context, cameraID string) bool {
	n, _ := q.rdb.Exists(ctx, "annotated:"+cameraID).Result()
	return n > 0
}

// Result は、worker が出した最新の認識結果（検出枠・追跡ID・最近の通過の JSON）。無ければ nil。
func (q *QueueRepository) Result(ctx context.Context, cameraID string) []byte {
	b, err := q.rdb.Get(ctx, "result:"+cameraID).Bytes()
	if err != nil {
		return nil
	}
	return b
}

// partitionOf は md5 の 16 バイトを大きな整数として扱い、n で割った余りを返す（Python の int(hexdigest, 16) % n と同じ）。
func partitionOf(cameraID string, n int) int {
	if n <= 1 {
		return 0
	}
	sum := md5Sum(cameraID)
	rem := 0
	for _, b := range sum { // 1 バイトずつ「余り」を更新すれば、大きな整数を作らずに余りが求まる
		rem = (rem*256 + int(b)) % n
	}
	return rem
}

func init() { _ = fmt.Sprint } // fmt を使わなくなっても import エラーにならないように
