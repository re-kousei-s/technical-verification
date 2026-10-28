import { api } from "../../api";
import { camLabel } from "../../lib/format";
import { useCamera, useOverview } from "../../hooks/useOverview";
import { Button } from "../ui/Button";

/** 端末 ID の、IN/OUT の履歴を消すボタン（フロアの人数の概算は変わらない） */
export function CameraResetButton({ cameraId }: { cameraId: string }) {
  const cam = useCamera(cameraId);
  const { refresh } = useOverview();
  const run = async () => {
    const label = cam ? camLabel(cam) : cameraId;
    if (!confirm(`${label}の IN/OUT の履歴（通過の記録と、端末ごとの累計）を消します。\nフロアの人数の概算は変わりません。元には戻せません。`)) return;
    try { await api.resetHistory({ camera_id: cameraId }); refresh(); } catch (e) { alert((e as Error).message); }
  };
  return <Button variant="danger" onClick={run}>IN/OUT 履歴を消す</Button>;
}
