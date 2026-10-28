import { useRef } from "react";
import { clampPt, inNormal, lineColor, segDist, shiftLine, type Pt } from "../../lib/lines";
import type { Line } from "../../types";

interface Props {
  lines: Line[];
  /** 表示している大きさ（px）。座標の割合をこれで掛けて描く */
  width: number;
  height: number;
  boxes?: [number, number, number, number, number][];
  /** 編集中のときだけ渡す */
  edit?: { selected: number; onSelect: (i: number) => void; onChange: (i: number, pts: Pt[]) => void };
}

type Drag = { i: number; k: number; start: Pt; orig: Pt[] }; // k=-1 は、線ごと動かす

/**
 * 映像の上に重ねる SVG。線・IN の向き・検出枠を描き、edit があるときは、マウス/指で線を動かせる。
 *   端の○をドラッグ → 線の形、線の上をドラッグ → 線ごと移動
 */
export function LineOverlay({ lines, width, height, boxes, edit }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);

  // 画面の位置 → 映像の割合
  const toFrac = (e: React.PointerEvent): Pt => {
    const r = svg.current!.getBoundingClientRect();
    return clampPt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
  };

  // 押した場所に近い、端の○か線を探す。○を先に探す（15px 以内）。なければ線の上（10px 以内）
  const hitTest = (p: Pt): { i: number; k: number } | null => {
    let best: { i: number; k: number; d: number } | null = null;
    lines.forEach((ln, i) => ln.line.forEach((pt, k) => {
      const d = Math.hypot((p[0] - pt[0]) * width, (p[1] - pt[1]) * height);
      if (d < 15 && (!best || d < best.d)) best = { i, k, d };
    }));
    if (best) return best;
    lines.forEach((ln, i) => {
      const px = (q: Pt): Pt => [q[0] * width, q[1] * height];
      const d = segDist(px(p), px(ln.line[0] as Pt), px(ln.line[1] as Pt));
      if (d < 10 && (!best || d < best.d)) best = { i, k: -1, d };
    });
    return best;
  };

  const onDown = (e: React.PointerEvent) => {
    if (!edit) return;
    const p = toFrac(e), hit = hitTest(p);
    if (!hit) return;
    edit.onSelect(hit.i);
    drag.current = { ...hit, start: p, orig: lines[hit.i].line.map((q) => [...q] as Pt) };
    svg.current!.setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || !edit) return;
    const p = toFrac(e);
    if (d.k >= 0) {
      const pts = d.orig.map((q) => [...q] as Pt);
      pts[d.k] = p;
      edit.onChange(d.i, pts);
    } else {
      edit.onChange(d.i, shiftLine(d.orig, p[0] - d.start[0], p[1] - d.start[1]));
    }
  };
  const onUp = () => { drag.current = null; };

  return (
    <svg
      ref={svg} width={width} height={height}
      className={`absolute inset-0 ${edit ? "cursor-crosshair" : "pointer-events-none"}`}
      style={{ touchAction: "none" }}
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
    >
      {boxes?.map(([x1, y1, x2, y2, id], i) => (
        <g key={i}>
          <rect x={x1 * width} y={y1 * height} width={(x2 - x1) * width} height={(y2 - y1) * height} fill="none" stroke="#34c759" strokeWidth={2} />
          {id >= 0 && <text x={x1 * width + 3} y={y1 * height - 4} fill="#34c759" fontSize={12} fontWeight={700}>#{id}</text>}
        </g>
      ))}
      {lines.map((ln, i) => {
        const col = lineColor(i);
        const [a, b] = ln.line.map(([x, y]) => [x * width, y * height] as Pt);
        const [nx, ny] = inNormal(a, b);
        const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, L = 34;
        const sel = !!edit && edit.selected === i;
        return (
          <g key={ln.id || i}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={col} strokeWidth={sel ? 5 : 3} />
            {/* IN の向き（緑の矢印）と OUT の向き */}
            <line x1={mx - nx * L / 2} y1={my - ny * L / 2} x2={mx + nx * L / 2} y2={my + ny * L / 2} stroke="#34c759" strokeWidth={4} />
            <polygon fill="#34c759" points={`${mx + nx * (L / 2 + 10)},${my + ny * (L / 2 + 10)} ${mx + nx * L / 2 - ny * 8},${my + ny * L / 2 + nx * 8} ${mx + nx * L / 2 + ny * 8},${my + ny * L / 2 - nx * 8}`} />
            <text x={mx + nx * (L / 2 + 16) - 8} y={my + ny * (L / 2 + 16) + 5} fill="#34c759" fontSize={13} fontWeight={700}>IN</text>
            <text x={mx - nx * (L / 2 + 18) - 12} y={my - ny * (L / 2 + 18) + 5} fill="#ff9500" fontSize={13} fontWeight={700}>OUT</text>
            <text x={a[0] + 8} y={a[1] - 10} fill={col} fontSize={13} fontWeight={700} stroke="#000" strokeWidth={0.5} paintOrder="stroke">{ln.name}</text>
            {[a, b].map((p, k) => (
              <circle key={k} cx={p[0]} cy={p[1]} r={edit ? 10 : 6} fill={col} stroke={sel ? "#fff" : "none"} strokeWidth={3} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}
