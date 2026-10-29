// バックエンドの API が返す形（キー名は Go 側の JSON と同じ）

export type Level = "blue" | "yellow" | "red" | null;

export interface ServiceStatus {
  redis: boolean;
  postgres: boolean;
  ingest: boolean;
  workers_alive: number;
  workers_total: number;
}

export interface QueueRow { partition: number; stream: string; length: number; pending: number; lag: number | null }

export interface WorkerRow {
  name: string; detector: string; partitions: string; processed: string; errors: string;
  infer_ms_avg: string; lag_ms_avg: string; age_ms: number; alive: boolean;
}

/** 映像の上に引く線。座標は、映像の幅・高さに対する割合（0〜1） */
export interface Line { id: string; name: string; line: [number, number][] }

export interface Camera {
  id: string; floor: number; name: string | null; sample_fps: number; tracker: string;
  anchor: string; lines: string[]; recognizing: boolean; phone_online: boolean; source: "db" | "yaml"; connected: boolean;
  last_seen_age_ms: number | null; decoded: number; enqueued: number; dropped: number; decode_errors: number;
  in: number; out: number; last_dets: number | null; last_tracks: number | null; last_frame_ts: string | null;
  size: [number | null, number | null]; has_image: boolean;
}

export interface FloorDevice { id: string; name: string | null; connected: boolean; in: number; out: number }

export interface Floor {
  floor: number; count: number; low: number; high: number; margin: number;
  crossings_since_correction: number; corrected_at: string | null; level: Level;
  thresholds: { yellow: number; red: number } | null; updated_at: string | null; cameras: FloorDevice[];
}

export interface Crossing {
  id: number; camera_id: string; floor: number | null; ts: string; direction: "in" | "out"; track_id: number; line_name: string | null;
}

export interface Perf {
  frames: number; infer_avg: number | null; infer_p95: number | null; lag_avg: number | null; lag_p95: number | null; dets_avg: number | null;
}

export interface Overview {
  now_ms: number; services: ServiceStatus; problems: string[]; queue: QueueRow[]; backlog: number;
  workers: WorkerRow[]; cameras: Camera[]; live_fps: number; floors: Floor[];
  recent_crossings: Crossing[]; perf_60s: Perf; totals: { crossings: number; frames: number };
}

/** /api/live/:id/info */
export interface LiveInfo {
  streaming: boolean; recognizing: boolean; phone_online: boolean; rx_fps: number | null;
  live_on: boolean; requested_fps: number; max_seconds: number;
  lines: Line[]; in: number; out: number; line_counts: Record<string, { in: number; out: number }>;
  caps: CameraCaps | null;
}

/** スマホが報告する、カメラの能力と、いまの設定 */
export interface CameraCaps {
  devices: { id: string; label: string }[]; device_id?: string; res: string; actual?: [number, number];
  resolutions: { value: string; label: string }[];
  zoom: { min: number; max: number; step: number; value: number } | null;
}

/** /api/camera/:id/result（[x1,y1,x2,y2,追跡ID]、座標は割合） */
export interface DetectResult { boxes?: [number, number, number, number, number][]; stale?: boolean }
