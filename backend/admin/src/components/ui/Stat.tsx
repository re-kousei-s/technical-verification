import type { ReactNode } from "react";

/** ラベルと値の組（端末の数字などに使う） */
export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "in" | "out" | "warn" }) {
  const color = tone === "in" ? "text-good" : tone === "out" ? "text-bad" : tone === "warn" ? "text-bad" : "text-ink";
  return (
    <div>
      <div className="text-xs text-sub">{label}</div>
      <div className={`text-base font-medium tabular-nums ${color}`}>{value}</div>
    </div>
  );
}
