import { Link, useParams } from "react-router-dom";
import { CameraLines } from "../components/camera/CameraLines";
import { CameraLiveView } from "../components/camera/CameraLiveView";
import { CameraSettingsPanel } from "../components/camera/CameraSettingsPanel";
import { CameraSnapshot } from "../components/camera/CameraSnapshot";
import { RecognizeButton } from "../components/camera/RecognizeButton";
import { CameraDeleteButton } from "../components/camera/CameraDeleteButton";
import { CameraResetButton } from "../components/camera/CameraResetButton";
import { CameraStats } from "../components/camera/CameraStats";
import { CrossingsTable } from "../components/CrossingsTable";
import { Card } from "../components/ui/Card";
import { Chip } from "../components/ui/Chip";
import { PageHeader } from "../components/ui/PageHeader";
import { camLabel } from "../lib/format";
import { useCamera } from "../hooks/useOverview";

/** 端末 1 台のページ。すべて、URL の端末 ID だけで決まる */
export default function CameraDetailPage() {
  const id = decodeURIComponent(useParams().id ?? "");
  const cam = useCamera(id);
  if (!cam) {
    return <p className="text-sub">端末 {id} は見つかりません。<Link className="text-primary" to="/cameras">端末の一覧へ</Link></p>;
  }
  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-3">{camLabel(cam)}<Chip tone={cam.connected ? "ok" : "off"} dot>{cam.connected ? "接続中" : "切断"}</Chip></span>}
        sub={`${cam.id} ／ ${cam.floor}階 ／ 認識 ${cam.sample_fps}fps ／ 認識の開始・停止、ライブ、線の編集は、ここから行います`}
        actions={<><RecognizeButton cameraId={cam.id} /><CameraResetButton cameraId={cam.id} /><CameraDeleteButton cameraId={cam.id} /></>}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card title="ライブ" className="min-w-0"><CameraLiveView cameraId={cam.id} /></Card>
        <div className="space-y-4">
          <Card title="カメラの設定（スマホ）"><CameraSettingsPanel cameraId={cam.id} /></Card>
          <Card title="数字"><CameraStats cameraId={cam.id} /></Card>
          <Card title="数える線"><CameraLines cameraId={cam.id} /></Card>
          <Card title="認識結果の画像（2 秒ごと）"><CameraSnapshot cameraId={cam.id} /></Card>
        </div>
      </div>
      <div className="mt-4">
        <Card title="この端末の通過" pad={false}><CrossingsTable cameraId={cam.id} /></Card>
      </div>
    </>
  );
}
