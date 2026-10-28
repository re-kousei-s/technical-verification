import { ago, fmt } from "../../lib/format";
import { useCamera } from "../../hooks/useOverview";
import { Stat } from "../ui/Stat";

/** 端末 ID の、数字の一覧（IN/OUT、検出、デコード、破棄 など） */
export function CameraStats({ cameraId }: { cameraId: string }) {
  const c = useCamera(cameraId);
  if (!c) return null;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
      <Stat label="IN" value={c.in} tone="in" />
      <Stat label="OUT" value={c.out} tone="out" />
      <Stat label="検出 / 追跡" value={`${fmt(c.last_dets)} / ${fmt(c.last_tracks)}`} />
      <Stat label="最終受信" value={ago(c.last_seen_age_ms)} />
      <Stat label="デコード" value={c.decoded} />
      <Stat label="キュー投入" value={c.enqueued} />
      <Stat label="破棄" value={c.dropped} tone={c.dropped ? "warn" : undefined} />
      <Stat label="デコード失敗" value={c.decode_errors} tone={c.decode_errors ? "warn" : undefined} />
    </div>
  );
}
