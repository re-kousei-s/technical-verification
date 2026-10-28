import { useCamera } from "../../hooks/useOverview";
import { lineColor } from "../../lib/lines";

const ANCHORS: Record<string, string> = {
  bottom_center: "足元（枠の下の中央）", top_center: "頭（枠の上の中央）", center: "枠の中心", box: "枠全体",
};

/** 端末 ID の、数える線の名前と、判定に使う位置 */
export function CameraLines({ cameraId }: { cameraId: string }) {
  const c = useCamera(cameraId);
  if (!c) return null;
  return (
    <div className="space-y-2 text-sm">
      <ul className="space-y-1">
        {c.lines.map((n, i) => (
          <li key={n} className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ background: lineColor(i) }} />{n}
          </li>
        ))}
      </ul>
      <div className="text-xs text-sub">判定に使う位置：{ANCHORS[c.anchor] ?? c.anchor}／ 追跡：{c.tracker}</div>
    </div>
  );
}
