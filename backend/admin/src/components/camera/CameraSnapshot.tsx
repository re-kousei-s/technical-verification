import { frameUrl } from "../../api";
import { useCamera, useOverview } from "../../hooks/useOverview";

/** 端末 ID の、検出枠つきの最新画像（ライブではなく、2 秒ごとに更新される静止画） */
export function CameraSnapshot({ cameraId }: { cameraId: string }) {
  const cam = useCamera(cameraId);
  const now = useOverview().data?.now_ms ?? 0;
  if (cam?.has_image) {
    return <img src={frameUrl(cameraId, now)} alt={cameraId} className="aspect-video w-full rounded-md bg-bg object-contain" />;
  }
  return (
    <div className="grid aspect-video w-full place-items-center rounded-md bg-bg text-sub">
      {cam?.connected ? "最初のフレームを待っています" : "未接続"}
    </div>
  );
}
