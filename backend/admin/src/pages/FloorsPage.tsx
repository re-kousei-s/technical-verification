import { FloorCard } from "../components/floor/FloorCard";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

export default function FloorsPage() {
  const { data } = useOverview();
  return (
    <>
      <PageHeader title="フロア" sub="範囲は「補正してからの通過件数 × 誤差率（仮 20%）」。人が数えた人数で補正すると、範囲が小さくなります" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data?.floors.map((f) => <FloorCard key={f.floor} floor={f} />)}
      </div>
      {data && !data.floors.length && <p className="text-sub">まだ端末が登録されていません</p>}
    </>
  );
}
