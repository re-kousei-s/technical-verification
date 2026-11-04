import { useDialog } from "../ui/DialogProvider";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { camLabel } from "../../lib/format";
import { useCamera, useOverview } from "../../hooks/useOverview";
import { Button } from "../ui/Button";

/** 端末 ID の、登録を削除するボタン。通過の記録は残る。接続中のスマホは、切られる */
export function CameraDeleteButton({ cameraId }: { cameraId: string }) {
  const dialog = useDialog();
  const cam = useCamera(cameraId);
  const { refresh } = useOverview();
  const nav = useNavigate();
  if (!cam) return null;

  const run = async () => {
    if (cam.source !== "db") {
      dialog.alert("この端末は、config/cameras.yaml の cameras: に書かれた、固定のテスト用です。\n画面からは、消せません。消すときは、cameras.yaml から、この端末の行を消してください（数秒で反映されます）。");
      return;
    }
    const msg = `${camLabel(cam)}（${cam.id}）の登録を削除します。\n` +
      "・これまでの通過の記録は、残ります。\n" +
      (cam.phone_online ? "・接続中のスマホは、切られます（スマホで、登録し直しが必要です）。\n" : "") +
      "元には戻せません。";
    if (!await dialog.confirm(msg)) return;
    try { await api.deleteCamera(cam.id); refresh(); nav("/cameras"); } catch (e) { dialog.alert((e as Error).message); }
  };
  return (
    <Button variant="danger" onClick={run}>
      端末を削除
    </Button>
  );
}
