import { CameraCard } from "../components/camera/CameraCard";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

export default function CamerasPage() {
  const { data } = useOverview();
  const cams = data?.cameras ?? [];
  return (
    <>
      <PageHeader
        title="端末" sub={`${cams.length} 台（接続中 ${cams.filter((c) => c.connected).length} 台）。押すと、ライブ表示と線の編集ができます`}
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cams.map((c) => <CameraCard key={c.id} cameraId={c.id} />)}
      </div>
      <p className="mt-6 text-xs text-sub">スマホで、送信ページ（https://このPCのIP:8000）を開くと、端末が登録されます。</p>
    </>
  );
}
