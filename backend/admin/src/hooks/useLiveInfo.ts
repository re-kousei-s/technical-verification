import { useEffect, useState } from "react";
import { api } from "../api";
import type { LiveInfo } from "../types";

/** 端末の状態（スマホの報告したカメラの能力を含む）を、2 秒ごとに読む */
export function useLiveInfo(cameraId: string): LiveInfo | null {
  const [info, setInfo] = useState<LiveInfo | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => api.liveInfo(cameraId).then((i) => alive && setInfo(i)).catch(() => {});
    tick();
    const t = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(t); };
  }, [cameraId]);
  return info;
}
