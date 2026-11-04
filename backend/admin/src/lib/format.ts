// 表示用の整形

export const fmt = (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(+v) ? "–" : (+v).toFixed(d));

/** 「何秒前」「何分前」 */
export const ago = (ms: number | null | undefined) =>
  ms == null ? "–" : ms < 1500 ? "今" : ms < 60000 ? `${Math.round(ms / 1000)}秒前` : `${Math.round(ms / 60000)}分前`;

export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("ja-JP", { hour12: false }) : "–";

/** 端末の表示名（名前が無ければ ID） */
export const camLabel = (c: { id: string; name: string | null }) => c.name || c.id;

/** 通信の速さ（kbps）を、読みやすく。1000 以上は Mbps */
export const fmtKbps = (k: number) => (k >= 1000 ? `${(k / 1000).toFixed(1)} Mbps` : `${Math.round(k)} kbps`);

/** 通信量（バイト）を、読みやすく */
export const fmtBytes = (b: number) =>
  b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(2)} GB` : b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`;
