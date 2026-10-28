import { useEffect, useState, type RefObject } from "react";
import { api } from "../api";
import { codecName, scanNals } from "../lib/h264";
import type { DetectResult, LiveInfo } from "../types";

export interface LiveState {
  /** 画面に出す状態の文言と、良し悪し */
  status: { text: string; tone: "ok" | "wait" | "bad" };
  info: LiveInfo | null;
  /** 映像の大きさ（最初のフレームが来るまで null） */
  size: { w: number; h: number } | null;
  /** 画面に出せている fps */
  shownFps: number | null;
}

/**
 * 端末 ID の映像を、canvas に出す。enabled が true の間だけ、つなぐ（見ようとしない間は、端末に高い fps を頼まない）。
 *   バックエンドが中継する H.264（Annex B）を WebSocket で受け取り、このブラウザの VideoDecoder（WebCodecs）でデコードする。
 *   サーバーはデコードしない。この部品が表示されている間だけ、端末は高い fps で送る（外すと元に戻る）。
 */
export function useCameraLive(cameraId: string, canvasRef: RefObject<HTMLCanvasElement>, enabled: boolean): LiveState {
  const [info, setInfo] = useState<LiveInfo | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [shownFps, setShownFps] = useState<number | null>(null);
  const [unsupported, setUnsupported] = useState(false);

  // 映像の受信とデコード
  useEffect(() => {
    if (!enabled) return;
    if (typeof VideoDecoder === "undefined") {
      setUnsupported(true);
      return;
    }
    setUnsupported(false);
    let decoder: VideoDecoder | null = null;
    let gotKey = false;
    let shown = 0;
    let shownAt = performance.now();

    const feed = (buf: Uint8Array) => {
      const cv = canvasRef.current;
      if (!cv) return;
      const { key, sps } = scanNals(buf);
      if (!decoder) {
        if (!key) return; // デコードはキーフレームから始める
        const g = cv.getContext("2d");
        decoder = new VideoDecoder({
          output: (frame) => {
            if (cv.width !== frame.displayWidth || cv.height !== frame.displayHeight) {
              cv.width = frame.displayWidth;
              cv.height = frame.displayHeight;
              setSize({ w: frame.displayWidth, h: frame.displayHeight });
            }
            g?.drawImage(frame, 0, 0);
            frame.close();
            shown++;
          },
          error: () => { decoder = null; gotKey = false; }, // 壊れたら捨てて、次のキーフレームからやり直す
        });
        decoder.configure({ codec: codecName(sps), optimizeForLatency: true });
      }
      if (!gotKey && !key) return;
      gotKey = true;
      try {
        decoder.decode(new EncodedVideoChunk({ type: key ? "key" : "delta", timestamp: Math.round(performance.now() * 1000), data: buf }));
      } catch {
        decoder = null;
        gotKey = false;
      }
    };

    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live/${encodeURIComponent(cameraId)}`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (e) => feed(new Uint8Array(e.data));

    const fpsTimer = window.setInterval(() => {
      const now = performance.now();
      setShownFps(shown / ((now - shownAt) / 1000));
      shown = 0;
      shownAt = now;
    }, 1000);

    return () => {
      window.clearInterval(fpsTimer);
      try { ws.close(); } catch { /* 閉じる途中でもよい */ }
      try { decoder?.close(); } catch { /* 既に閉じている */ }
      const cv = canvasRef.current;
      cv?.getContext("2d")?.clearRect(0, 0, cv.width, cv.height);
      setSize(null);
    };
  }, [cameraId, canvasRef, enabled]);

  // 端末の状態・線・IN/OUT（1 秒ごと）
  useEffect(() => {
    let alive = true;
    const tick = () => api.liveInfo(cameraId).then((i) => alive && setInfo(i)).catch(() => {});
    tick();
    const t = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(t); };
  }, [cameraId]);

  let status: LiveState["status"];
  if (!enabled) status = { text: "ライブは停止中です（見るときは「ライブを開始」）", tone: "wait" };
  else if (unsupported) status = { text: "この画面ではデコードできません（HTTPS か localhost で開いてください）", tone: "bad" };
  else if (info?.streaming) status = { text: info.mode === "live" ? "ライブ中（プレビューのみ・認識なし）" : "ライブ中（送信中の端末）", tone: "ok" };
  else if (info?.ctl_online) status = { text: "端末に配信を頼んでいます…", tone: "wait" };
  else status = { text: "スマホで送信ページを開いておいてください（画面は点けたまま）", tone: "bad" };

  return { status, info, size, shownFps };
}

/** 検出枠（認識の頻度でしか更新されない）。enabled が false の間は取りに行かない */
export function useDetectBoxes(cameraId: string, enabled: boolean): DetectResult | null {
  const [r, setR] = useState<DetectResult | null>(null);
  useEffect(() => {
    if (!enabled) { setR(null); return; }
    let alive = true;
    const tick = () => api.result(cameraId).then((x) => alive && setR(x)).catch(() => {});
    tick();
    const t = window.setInterval(tick, 250);
    return () => { alive = false; window.clearInterval(t); };
  }, [cameraId, enabled]);
  return r;
}
