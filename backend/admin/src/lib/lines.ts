// 線の計算。座標はすべて「映像に対する割合（0〜1）」。

import type { Line } from "../types";

export type Pt = [number, number];

/** 線ごとの色（映像の上で、線を見分けるため） */
export const LINE_COLORS = ["#ff3b30", "#ffcc00", "#00c7ff", "#ff7ad9", "#7dff7a", "#b388ff"];
export const lineColor = (i: number) => LINE_COLORS[i % LINE_COLORS.length];

export const MAX_LINES = 12;

/** 点 p から線分 a-b までの距離 */
export function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

/** 線ごと動かす。映像からはみ出さないよう、動かせる量を絞る */
export function shiftLine(orig: Pt[], dx: number, dy: number): Pt[] {
  const xs = orig.map((p) => p[0]), ys = orig.map((p) => p[1]);
  const x = Math.max(-Math.min(...xs), Math.min(1 - Math.max(...xs), dx));
  const y = Math.max(-Math.min(...ys), Math.min(1 - Math.max(...ys), dy));
  return orig.map((p) => [p[0] + x, p[1] + y]);
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
export const clampPt = (x: number, y: number): Pt => [clamp01(x), clamp01(y)];

/** 新しい線（水平で、既にある線より少し下） */
export function newLine(existing: Line[]): Line {
  let n = existing.length + 1;
  while (existing.some((l) => l.name === `線${n}`)) n++;
  const y = Math.min(0.9, 0.5 + existing.length * 0.06);
  return { id: "l" + Date.now().toString(36), name: `線${n}`, line: [[0.3, y], [0.6, y]] };
}

/** IN の向きの単位ベクトル（始点→終点に対して画面の左側。サーバーの LineZone と同じ） */
export function inNormal(a: Pt, b: Pt): Pt {
  const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
  return [dy / len, -dx / len];
}
