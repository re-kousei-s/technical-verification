import { Link } from "react-router-dom";
import { camLabel } from "../../lib/format";
import { useCamera } from "../../hooks/useOverview";
import { Chip } from "../ui/Chip";
import { CameraSnapshot } from "./CameraSnapshot";
import { CameraStats } from "./CameraStats";

/** 一覧に並べる、端末 1 台のカード。押すと、その端末のページ（ライブ・線の編集）へ */
export function CameraCard({ cameraId }: { cameraId: string }) {
  const c = useCamera(cameraId);
  if (!c) return null;
  return (
    <Link to={`/cameras/${encodeURIComponent(c.id)}`}
      className="block rounded-lg border border-line bg-surface p-4 shadow-sm transition hover:shadow-card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <b className="text-[15px]">{camLabel(c)}</b>
        {c.name && <span className="text-xs text-sub">{c.id}</span>}
        <Chip tone={c.recognizing ? (c.connected ? "ok" : "warn") : "off"} dot>{c.recognizing ? (c.connected ? "認識中" : "開始待ち") : "停止中"}</Chip>
        {c.source === "yaml" && <Chip tone="info">固定</Chip>}
        <span className="ml-auto text-xs text-sub">{c.floor}階 ／ {c.sample_fps}fps ／ 線 {c.lines.length}本</span>
      </div>
      <CameraSnapshot cameraId={c.id} />
      <div className="mt-3"><CameraStats cameraId={c.id} /></div>
    </Link>
  );
}
