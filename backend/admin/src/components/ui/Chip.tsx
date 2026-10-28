import type { ReactNode } from "react";

type Tone = "ok" | "bad" | "warn" | "info" | "off";

const TONES: Record<Tone, string> = {
  ok: "bg-good-soft text-good",
  bad: "bg-bad-soft text-bad",
  warn: "bg-warn-soft text-warn",
  info: "bg-primary-soft text-primary",
  off: "bg-line/50 text-sub",
};

/** 小さな状態表示（接続中・切断・青/黄/赤 など） */
export function Chip({ tone = "off", dot = false, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {dot && <span className="h-2 w-2 rounded-full bg-current" />}
      {children}
    </span>
  );
}
