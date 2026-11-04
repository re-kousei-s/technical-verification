import { useDialog } from "../ui/DialogProvider";
import type { ReactNode } from "react";
import { api } from "../../api";
import { useOverview } from "../../hooks/useOverview";
import type { Floor } from "../../types";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";

const LEVELS = { blue: { label: "青", tone: "info" as const }, yellow: { label: "黄", tone: "warn" as const }, red: { label: "赤", tone: "bad" as const } };

/** フロア 1 つぶんの見出し（人数の概算・補正）と、端末のタイルを並べる場所 */
export function FloorSection({ floor: f, children }: { floor: Floor; children: ReactNode }) {
  const dialog = useDialog();
  const { refresh } = useOverview();
  const lv = f.level ? LEVELS[f.level] : null;
  const correct = async () => {
    const v = await dialog.prompt(`${f.floor}階の人数を、実際の人数に直します`, String(f.count));
    if (v === null) return;
    const n = parseInt(v, 10);
    if (Number.isNaN(n) || n < 0) return dialog.alert("0 以上の整数を入力してください");
    try { await api.setFloorCount(f.floor, n); refresh(); } catch (e) { dialog.alert((e as Error).message); }
  };
  return (
    <section className="mb-8">
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium">{f.floor}階</h2>
        <span className="text-2xl tabular-nums">約 {f.count}<span className="ml-1 text-sm text-sub">人</span></span>
        <span className="text-sm text-sub">{f.margin ? `範囲 ${f.low}〜${f.high} 人` : "範囲 ±0"}</span>
        {lv && <Chip tone={lv.tone}>{lv.label}</Chip>}
        <Button variant="text" onClick={correct} className="ml-auto">人数を補正</Button>
      </header>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{children}</div>
    </section>
  );
}
