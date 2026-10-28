// 表示用の整形

export const fmt = (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(+v) ? "–" : (+v).toFixed(d));

/** 「何秒前」「何分前」 */
export const ago = (ms: number | null | undefined) =>
  ms == null ? "–" : ms < 1500 ? "今" : ms < 60000 ? `${Math.round(ms / 1000)}秒前` : `${Math.round(ms / 60000)}分前`;

export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("ja-JP", { hour12: false }) : "–";

/** 端末の表示名（名前が無ければ ID） */
export const camLabel = (c: { id: string; name: string | null }) => c.name || c.id;
