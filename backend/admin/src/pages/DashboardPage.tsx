import { Link } from "react-router-dom";
import { CameraCard } from "../components/camera/CameraCard";
import { CrossingsTable } from "../components/CrossingsTable";
import { FloorCard } from "../components/floor/FloorCard";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

/** 全体を一目で見る画面：フロアの人数、端末、直近の通過 */
export default function DashboardPage() {
  const { data } = useOverview();
  if (!data) return <p className="text-sub">読み込み中…</p>;
  return (
    <>
      <PageHeader title="ダッシュボード" sub="フロアの人数の概算は、全端末の IN − OUT の合算です" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {data.floors.length
          ? data.floors.map((f) => <FloorCard key={f.floor} floor={f} />)
          : <p className="text-sub">まだ端末が登録されていません</p>}
      </div>

      <h2 className="mb-3 mt-8 flex items-baseline gap-3 text-[15px] font-medium">
        端末 <Link to="/cameras" className="text-xs font-normal text-primary hover:underline">すべて見る</Link>
      </h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.cameras.slice(0, 6).map((c) => <CameraCard key={c.id} cameraId={c.id} />)}
      </div>

      <div className="mt-8">
        <Card title="直近の通過" pad={false}><CrossingsTable limit={10} /></Card>
      </div>
    </>
  );
}
