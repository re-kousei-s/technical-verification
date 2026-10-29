import { useContext, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCameraLive } from "../../hooks/useCameraLive";
import { useCamera } from "../../hooks/useOverview";
import { camLabel } from "../../lib/format";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { BulkPreviewContext } from "./BulkPreviewContext";
import { CameraSnapshot } from "./CameraSnapshot";

/**
 * 監視カメラの画面のような、1 台ぶんのタイル。端末 ID を渡すだけ。
 *   未接続      … 「未接続」と出す
 *   接続中      … 「プレビューを見る」ボタン（押すと、低い fps の映像。一括プレビューが入っていれば、最初から映る）
 *   認識中      … 現在の IN / OUT を、自動で更新して大きく出す（プレビューも入れれば、映像の上に出る）
 * タイルを押すと、その端末のページへ（線の調整・リアルタイム表示・カメラの設定）。
 * 映像は、プレビューが入っている間だけ、スマホが低い fps（thumb_fps）で送る。
 */
export function CameraTile({ cameraId }: { cameraId: string }) {
  const cam = useCamera(cameraId);
  const nav = useNavigate();
  const bulk = useContext(BulkPreviewContext);
  const [local, setLocal] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const online = !!cam?.phone_online;
  const previewing = online && (bulk || local);
  const live = useCameraLive(cameraId, canvas, previewing ? "thumb" : "off");
  if (!cam) return null;

  const state = cam.recognizing ? (cam.connected ? "認識中" : "開始待ち") : online ? "接続中" : "未接続";
  const tone = cam.recognizing ? (cam.connected ? "ok" : "warn") : online ? "info" : "off";
  return (
    <div role="link" tabIndex={0} onClick={() => nav(`/cameras/${encodeURIComponent(cam.id)}`)}
      onKeyDown={(e) => e.key === "Enter" && nav(`/cameras/${encodeURIComponent(cam.id)}`)}
      className="group relative block cursor-pointer overflow-hidden rounded-lg border border-line bg-black shadow-sm transition hover:shadow-card">
      <div className="relative aspect-video w-full">
        {previewing ? (
          <>
            <canvas ref={canvas} className="absolute inset-0 h-full w-full object-contain" />
            {!live.size && <div className="absolute inset-0 grid place-items-center text-sm text-white/60">映像を待っています…</div>}
          </>
        ) : !online ? (
          cam.source === "yaml"
            ? <div className="absolute inset-0 bg-surface"><CameraSnapshot cameraId={cam.id} /></div>
            : <div className="absolute inset-0 grid place-items-center bg-surface text-sm text-sub">未接続</div>
        ) : (
          <div className="absolute inset-0 grid place-items-center bg-surface">
            {cam.recognizing ? (
              <div className="text-center">
                <div className="text-xs text-sub">現在の通過</div>
                <div className="mt-1 text-4xl font-medium tabular-nums"><span className="text-good">IN {cam.in}</span><span className="mx-3 text-sub">/</span><span className="text-bad">OUT {cam.out}</span></div>
              </div>
            ) : (
              <Button variant="filled" onClick={(e) => { e.stopPropagation(); setLocal(true); }}>プレビューを見る</Button>
            )}
          </div>
        )}
        <div className="absolute inset-x-0 top-0 flex items-center gap-2 bg-gradient-to-b from-black/70 to-transparent p-2">
          <b className="text-sm text-white">{camLabel(cam)}</b>
          <span className="text-xs text-white/70">{cam.floor}階</span>
          <span className="ml-auto"><Chip tone={tone} dot>{state}</Chip></span>
        </div>
        {/* 映像を出しているときは、IN/OUT を下に重ねる */}
        {previewing && (
          <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 bg-gradient-to-t from-black/70 to-transparent p-2 text-xs font-bold text-white">
            <span className="text-good">IN {cam.in}</span><span className="text-bad">OUT {cam.out}</span>
            {local && !bulk && (
              <button className="ml-auto rounded-full bg-white/20 px-2 py-0.5 font-normal hover:bg-white/30"
                onClick={(e) => { e.stopPropagation(); setLocal(false); }}>プレビューを止める</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
