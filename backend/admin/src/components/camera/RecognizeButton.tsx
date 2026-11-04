import { useDialog } from "../ui/DialogProvider";
import { useState } from "react";
import { api } from "../../api";
import { useCamera, useOverview } from "../../hooks/useOverview";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";

/**
 * 端末 ID の「認識の開始・停止」。認識を始めるかどうかは、管理画面が決める。
 * スマホは、この指示に従って、「認識中」の間だけ映像を送る（数秒で切り替わる）。
 */
export function RecognizeButton({ cameraId }: { cameraId: string }) {
  const dialog = useDialog();
  const cam = useCamera(cameraId);
  const { refresh } = useOverview();
  const [busy, setBusy] = useState(false);
  if (!cam) return null;

  const toggle = async () => {
    setBusy(true);
    try { await api.setRecognize(cam.id, !cam.recognizing); refresh(); } catch (e) { dialog.alert((e as Error).message); } finally { setBusy(false); }
  };
  const sending = cam.connected; // 認識用の映像が、実際に届いているか
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Chip tone={cam.phone_online ? "ok" : "off"} dot>{cam.phone_online ? "スマホ接続中" : "スマホ未接続"}</Chip>
      <Chip tone={cam.recognizing ? (sending ? "ok" : "warn") : "off"} dot>
        {cam.recognizing ? (sending ? "認識中" : "認識を開始しています…") : "停止中"}
      </Chip>
      <Button variant={cam.recognizing ? "danger" : "filled"} onClick={toggle} disabled={busy || cam.source !== "db"}
        title={cam.source !== "db" ? "yaml で固定した端末には、スマホがありません" : !cam.phone_online ? "スマホで送信ページを開くと、開始されます" : ""}>
        {cam.recognizing ? "認識を停止" : "認識を開始"}
      </Button>
    </div>
  );
}
