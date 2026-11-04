import type { Crossing, DetectResult, Line, LiveInfo, Overview } from "./types";

// バックエンド（管理画面ポート）への問い合わせ。失敗したら Error を投げる（メッセージは画面にそのまま出せる）

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(j.detail || `通信に失敗しました（${res.status}）`);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});


export const api = {
  overview: () => request<Overview>("/api/overview"),
  liveInfo: (id: string) => request<LiveInfo>(`/api/live/${encodeURIComponent(id)}/info`),
  result: (id: string) => request<DetectResult>(`/api/camera/${encodeURIComponent(id)}/result`),
  crossings: (cameraId?: string, limit = 100) =>
    request<Crossing[]>(`/api/crossings?limit=${limit}` + (cameraId ? `&camera_id=${encodeURIComponent(cameraId)}` : "")),
  saveLines: (id: string, lines: Line[]) => request(`/api/camera/${encodeURIComponent(id)}/lines`, json("PUT", lines)),
  addCamera: (floor: number, name: string) => request<{ id: string }>("/api/cameras", json("POST", { floor, name })),
  deleteCamera: (id: string) => request(`/api/camera/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setFloorCount: (floor: number, count: number) => request(`/api/floors/${floor}/count`, json("POST", { count })),
  setRecognize: (id: string, on: boolean) => request(`/api/camera/${encodeURIComponent(id)}/recognize`, json("POST", { on })),
  setCameraSettings: (id: string, body: { res?: string; zoom?: number; device_id?: string; bitrate?: number }) =>
    request(`/api/camera/${encodeURIComponent(id)}/camera-settings`, json("PUT", body)),
  recognizeAll: (on: boolean) => request<{ cameras: number }>("/api/recognize/all", json("POST", { on })),
  resetHistory: (scope: { camera_id?: string; floor?: number }) => request("/api/history/reset", json("POST", scope)),
  resetFloors: () => request("/api/floors/reset", json("POST", {})),
  resetAll: () => request("/api/reset-all", json("POST", {})),
};

/** 検出枠つきの最新画像の URL（t を変えて、ブラウザのキャッシュを避ける） */
export const frameUrl = (id: string, t: number) => `/api/camera/${encodeURIComponent(id)}/frame.jpg?t=${t}`;
