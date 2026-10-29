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
  /** 認識結果（検出枠など）。映像と同じ接続で、変わったときに届く */
  result: DetectResult | null;
}

/**
 * 端末 ID の映像を、canvas に出す。enabled が true の間だけ、つなぐ（見ようとしない間は、端末に高い fps を頼まない）。
 *   バックエンドが中継する H.264（Annex B）を WebSocket で受け取り、このブラウザの VideoDecoder（WebCodecs）でデコードする。
 *   サーバーはデコードしない。この部品が表示されている間だけ、端末は高い fps で送る（外すと元に戻る）。
 */
/** off＝つながない / thumb＝一覧の小さな表示（低い fps） / live＝リアルタイム表示（高い fps を頼む） */
export type LiveMode = "off" | "thumb" | "live";

export function useCameraLive(cameraId: string, canvasRef: RefObject<HTMLCanvasElement>, mode: LiveMode): LiveState {
  const enabled = mode !== "off";
  const [info, setInfo] = useState<LiveInfo | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [shownFps, setShownFps] = useState<number | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  const [result, setResult] = useState<DetectResult | null>(null);

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

    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live/${encodeURIComponent(cameraId)}${mode === "thumb" ? "?thumb=1" : ""}`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (e) => {
      if (typeof e.data === "string") { try { setResult(JSON.parse(e.data)); } catch { /* 読めない結果は、使わない */ } return; }
      feed(new Uint8Array(e.data));
    };

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
      setResult(null);
    };
  }, [cameraId, canvasRef, enabled, mode]);

  // 端末の状態・線・IN/OUT（1 秒ごと）
  useEffect(() => {
    let alive = true;
    const tick = () => api.liveInfo(cameraId).then((i) => alive && setInfo(i)).catch(() => {});
    tick();
    const t = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(t); };
  }, [cameraId]);

  let status: LiveState["status"];
  if (!enabled) status = { text: "停止中", tone: "wait" };
  else if (unsupported) status = { text: "この画面ではデコードできません（HTTPS か localhost で開いてください）", tone: "bad" };
  else if (info?.streaming) status = { text: (mode === "live" ? "リアルタイム" : "低 fps") + (info.recognizing ? "（認識中）" : "（認識していない）"), tone: "ok" };
  else if (info?.phone_online) status = { text: "端末に配信を頼んでいます…", tone: "wait" };
  else status = { text: "スマホで送信ページを開いておいてください（画面は点けたまま）", tone: "bad" };

  return { status, info, size, shownFps, result };
}
