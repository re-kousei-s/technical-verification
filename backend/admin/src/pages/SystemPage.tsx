import { Card } from "../components/ui/Card";
import { Chip } from "../components/ui/Chip";
import { DataTable } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { Stat } from "../components/ui/Stat";
import { fmt } from "../lib/format";
import { useOverview } from "../hooks/useOverview";

/** キュー・worker・処理時間（システムの健康状態） */
export default function SystemPage() {
  const { data } = useOverview();
  if (!data) return <p className="text-sub">読み込み中…</p>;
  const p = data.perf_60s;
  return (
    <>
      <PageHeader title="システム" sub={`キューの待ち ${data.backlog} 件`} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="キュー（Redis Streams）" pad={false}>
          <DataTable rows={data.queue} rowKey={(q) => q.stream} empty="キューなし" columns={[
            { header: "パーティション", cell: (q) => `p${q.partition}` },
            { header: "待ち", align: "right", cell: (q) => q.length },
            { header: "処理中（未ACK）", align: "right", cell: (q) => q.pending },
            { header: "未配信", align: "right", cell: (q) => q.lag ?? "–" },
          ]} />
        </Card>
        <Card title="直近 60 秒の処理">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label="処理したフレーム" value={p.frames} />
            <Stat label="1 秒あたり" value={fmt(p.frames / 60, 2)} />
            <Stat label="検出数（平均）" value={fmt(p.dets_avg, 1)} />
            <Stat label="推論 平均 / p95 (ms)" value={`${fmt(p.infer_avg)} / ${fmt(p.infer_p95)}`} />
            <Stat label="遅れ 平均 / p95 (ms)" value={`${fmt(p.lag_avg)} / ${fmt(p.lag_p95)}`} />
            <Stat label="累計 通過 / フレーム" value={`${data.totals.crossings} / ${data.totals.frames}`} />
          </div>
        </Card>
        <Card title="worker" pad={false} className="xl:col-span-2">
          <DataTable rows={data.workers} rowKey={(w) => w.name} empty="worker が登録されていません" columns={[
            { header: "名前", cell: (w) => w.name },
            { header: "状態", cell: (w) => <Chip tone={w.alive ? "ok" : "bad"} dot>{w.alive ? "稼働" : "停止"}</Chip> },
            { header: "検出器", cell: (w) => w.detector },
            { header: "担当", cell: (w) => `p${w.partitions}` },
            { header: "処理", align: "right", cell: (w) => w.processed },
            { header: "失敗", align: "right", cell: (w) => w.errors, className: (w) => (+w.errors ? "text-bad" : "") },
            { header: "推論 ms", align: "right", cell: (w) => w.infer_ms_avg },
            { header: "遅れ ms", align: "right", cell: (w) => w.lag_ms_avg },
          ]} />
        </Card>
      </div>
    </>
  );
}
