import { api } from "../../api";
import { camLabel } from "../../lib/format";
import { useOverview } from "../../hooks/useOverview";
import type { Floor } from "../../types";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";

const LEVELS = {
  blue: { label: "青", bar: "bg-primary", chip: "info" as const },
  yellow: { label: "黄", bar: "bg-warn", chip: "warn" as const },
  red: { label: "赤", bar: "bg-bad", chip: "bad" as const },
};

/** フロア 1 つぶんの、人数の概算と、補正・履歴リセット */
export function FloorCard({ floor: f }: { floor: Floor }) {
  const { data, refresh } = useOverview();
  const lv = f.level ? LEVELS[f.level] : null;
  const names = (id: string) => { const c = data?.cameras.find((x) => x.id === id); return c ? camLabel(c) : id; };

  const correct = async () => {
    const v = prompt(`${f.floor}階の人数を、実際の人数に直します`, String(f.count));
    if (v === null) return;
    const n = parseInt(v, 10);
    if (Number.isNaN(n) || n < 0) return alert("0 以上の整数を入力してください");
    try { await api.setFloorCount(f.floor, n); refresh(); } catch (e) { alert((e as Error).message); }
  };
  const resetHistory = async () => {
    if (!confirm(`${f.floor}階の IN/OUT の履歴を消します。\nフロアの人数の概算は変わりません。元には戻せません。`)) return;
    try { await api.resetHistory({ floor: f.floor }); refresh(); } catch (e) { alert((e as Error).message); }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
      <div className={`h-1.5 ${lv?.bar ?? "bg-line"}`} />
      <div className="p-4">
        <div className="flex items-center gap-2">
          <b className="text-[15px]">{f.floor}階</b>
          {lv && <Chip tone={lv.chip}>{lv.label}</Chip>}
          {f.thresholds && <span className="ml-auto text-xs text-sub">黄 {f.thresholds.yellow} ／ 赤 {f.thresholds.red}（仮）</span>}
        </div>
        <div className="mt-2 text-4xl font-normal tabular-nums">約 {f.count}<span className="ml-1 text-sm text-sub">人</span></div>
        <div className="mt-1 text-sm text-sub">
          {f.margin ? `範囲 ${f.low}〜${f.high} 人（通過 ${f.crossings_since_correction} 件）` : "範囲 ±0（通過 0 件）"}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {f.cameras.length ? f.cameras.map((c) => (
            <Chip key={c.id} tone={c.connected ? "ok" : "off"} dot>{names(c.id)}</Chip>
          )) : <span className="text-xs text-sub">端末なし</span>}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outlined" onClick={correct}>人数を補正</Button>
          <Button variant="text" onClick={resetHistory}>IN/OUT 履歴を消す</Button>
        </div>
      </div>
    </div>
  );
}
