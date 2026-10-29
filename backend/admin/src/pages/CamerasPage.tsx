import { CameraTile } from "../components/camera/CameraTile";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

export default function CamerasPage() {
  const { data } = useOverview();
  const cams = data?.cameras ?? [];
  return (
    <>
      <PageHeader
        title="端末" sub={`${cams.length} 台（接続中 ${cams.filter((c) => c.connected).length} 台）。スマホがつながっている端末は、低い fps の映像が自動で映ります。押すと、リアルタイム表示・線の調整・認識の開始ができます`}
      />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {cams.map((c) => <CameraTile key={c.id} cameraId={c.id} />)}
      </div>
      <p className="mt-6 text-xs text-sub">スマホで、送信ページ（https://このPCのIP:8000）を開くと、端末が登録されます。</p>
    </>
  );
}
