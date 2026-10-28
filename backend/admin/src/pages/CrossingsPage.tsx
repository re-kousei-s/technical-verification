import { CrossingsTable } from "../components/CrossingsTable";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

export default function CrossingsPage() {
  const t = useOverview().data?.totals;
  return (
    <>
      <PageHeader title="通過の履歴" sub={t ? `累計 ${t.crossings} 件（処理したフレーム ${t.frames}）。新しい順に 100 件まで表示します` : undefined} />
      <Card pad={false}><CrossingsTable limit={100} /></Card>
    </>
  );
}
