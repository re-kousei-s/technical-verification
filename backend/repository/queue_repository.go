package repository

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"
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

	mu    sync.Mutex
	cache map[string]int // 端末 ID → 分割（Redis の割り当てを、覚えておく）
}

// assignKey は、端末 → 分割の割り当て（Redis のハッシュ）。一度決めたら、ずっと同じ分割（追跡の状態が、worker に残るため）
const assignKey = "camera_partition"

func NewQueueRepository(rdb *redis.Client, partitions int) *QueueRepository {
	return &QueueRepository{rdb: rdb, partitions: partitions, cache: map[string]int{}}
}

func (q *QueueRepository) Ping(ctx context.Context) error { return q.rdb.Ping(ctx).Err() }

// PartitionOf は、端末をどのキュー（= どの worker）に振るかを決める。
// 同じ端末のフレームは、必ず同じ分割に届く（追跡の状態を持つため）。分割は、いずれかの worker が持つ（worker 側が、自動で分け合う）。
//
// 初めて見る端末は、**端末がいちばん少ない分割**に振る（ハッシュだと、2 台が同じ分割に重なって、worker を増やしても、1 台ぶんの
// 負荷のままになることがある）。一度決めたら、Redis に残して、変えない。端末を削除したら、ReleasePartition で、空ける。
func (q *QueueRepository) PartitionOf(cameraID string) int {
	q.mu.Lock()
	if p, ok := q.cache[cameraID]; ok {
		q.mu.Unlock()
		return p
	}
	q.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	p, err := q.rdb.HGet(ctx, assignKey, cameraID).Int()
	if err != nil || p < 0 || p >= q.partitions {
		all, err := q.rdb.HGetAll(ctx, assignKey).Result()
		if err != nil {
			return partitionOf(cameraID, q.partitions) // Redis が答えないときは、ハッシュで代用（覚えない）
		}
		count := make([]int, q.partitions)
		for _, s := range all {
			if n, e := strconv.Atoi(s); e == nil && n >= 0 && n < q.partitions {
				count[n]++
			}
		}
		// 分割は、worker が分け合って持つ（鍵 partition_lock:{n} の値が、持ち主の名前）。
		// 端末の数が、いちばん少ない worker の分割に振る。同じ worker の中では、端末がいちばん少ない分割に振る
		// （端末が少ないだけの分割を選ぶと、2 台が、同じ worker の分割に重なって、worker を増やしても、1 台ぶんの負荷のままになる）
		owner := make([]string, q.partitions)
		load := map[string]int{} // worker 名 → その worker が持つ分割にいる、端末の数
		for i := range owner {
			owner[i], _ = q.rdb.Get(ctx, "partition_lock:"+strconv.Itoa(i)).Result()
			load[owner[i]] += count[i]
		}
		best := 0
		cost := func(i int) (int, int) {
			if owner[i] == "" {
				return 1 << 20, count[i] // 持ち主がいない分割（worker が、足りない）は、最後に
			}
			return load[owner[i]], count[i]
		}
		for i := 1; i < q.partitions; i++ {
			li, ci := cost(i)
			lb, cb := cost(best)
			if li < lb || (li == lb && ci < cb) {
				best = i
			}
		}
		_ = q.rdb.HSetNX(ctx, assignKey, cameraID, best).Err() // 同時に決めても、先に書いた 1 つが、残る
		if p, err = q.rdb.HGet(ctx, assignKey, cameraID).Int(); err != nil {
			return best
		}
	}
	q.mu.Lock()
	q.cache[cameraID] = p
	q.mu.Unlock()
	return p
}

// ReleasePartition は、端末を削除したとき、割り当てを空ける（次に追加された端末が、その分割を使える）。
func (q *QueueRepository) ReleasePartition(ctx context.Context, cameraID string) {
	q.mu.Lock()
	delete(q.cache, cameraID)
	q.mu.Unlock()
	_ = q.rdb.HDel(ctx, assignKey, cameraID).Err()
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
