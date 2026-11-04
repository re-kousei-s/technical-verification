import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useLiveInfo } from "../../hooks/useLiveInfo";
import { useCamera } from "../../hooks/useOverview";

/** 選べるビットレート（kbps）。低くしても、認識に足りることが多い（解像度・fps が低いとき） */
const BITRATES = [256, 512, 768, 1000, 1500, 2000, 3000];

const SELECT = "h-9 w-full rounded-lg border border-line bg-surface px-2 text-sm";

/**
 * 端末 ID の、スマホのカメラの設定（配信のビットレート・カメラの選択・解像度・ズーム）。管理画面で決めると、スマホが従う。
 *   ビットレートは、スマホが接続していなくても、決められる（次に接続したとき、スマホに伝わる）。
 *   カメラ・解像度・ズームの選べる内容は、スマホが報告したもの（スマホの送信ページが開いている間だけ）。
 */
export function CameraSettingsPanel({ cameraId }: { cameraId: string }) {
  const cam = useCamera(cameraId);
  const info = useLiveInfo(cameraId);
  const caps = info?.caps ?? null;
  const [msg, setMsg] = useState("");
  const [zoom, setZoom] = useState<number | null>(null);
  const timer = useRef<number>();
  useEffect(() => { if (caps?.zoom && zoom === null) setZoom(caps.zoom.value); }, [caps, zoom]);

  if (cam?.source !== "db") return <p className="text-sm text-sub">固定の端末には、スマホがありません。</p>;

  const send = async (body: { res?: string; zoom?: number; device_id?: string; bitrate?: number }) => {
    try { await api.setCameraSettings(cameraId, body); setMsg("送りました。スマホに、数秒で反映されます"); }
    catch (e) { setMsg((e as Error).message); }
  };

  return (
    <div className="space-y-3 text-sm">
      {/* ビットレート：スマホの接続に関係なく、いつでも決められる */}
      <label className="block">
        <span className="text-xs text-sub">配信のビットレート（低いほど、通信と電池を節約。画質は、下がる）</span>
        <select className={SELECT} value={info?.camera_settings?.bitrate ?? 0} onChange={(e) => send({ bitrate: +e.target.value })}>
          <option value={0}>自動（解像度と fps から決める）</option>
          {BITRATES.map((k) => <option key={k} value={k}>{k >= 1000 ? `${k / 1000} Mbps` : `${k} kbps`}</option>)}
        </select>
      </label>

      {!caps ? (
        <p className="text-xs text-sub">
          {info?.phone_online
            ? "カメラ・解像度・ズームは、スマホからの報告を待っています（届かないときは、スマホの送信ページを開き直してください）。"
            : "カメラ・解像度・ズームは、スマホが接続すると、選べます。"}
        </p>
      ) : (
        <>
          <label className="block">
            <span className="text-xs text-sub">カメラ（広角レンズなど）</span>
            <select className={SELECT} value={caps.device_id} onChange={(e) => send({ device_id: e.target.value })}>
              {caps.devices.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-sub">解像度・縦横比</span>
            <select className={SELECT} value={caps.res} onChange={(e) => send({ res: e.target.value })}>
              {caps.resolutions.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
          {caps.zoom && (
            <label className="block">
              <span className="text-xs text-sub">ズーム ×{(zoom ?? caps.zoom.value).toFixed(1)}（{caps.zoom.min}〜{caps.zoom.max}）</span>
              <input type="range" className="w-full" min={caps.zoom.min} max={caps.zoom.max} step={caps.zoom.step}
                value={zoom ?? caps.zoom.value}
                onChange={(e) => {
                  const v = +e.target.value; setZoom(v);
                  window.clearTimeout(timer.current);
                  timer.current = window.setTimeout(() => send({ zoom: v }), 400); // つまみを動かし終わってから送る
                }} />
            </label>
          )}
          {caps.actual && <p className="text-xs text-sub">いまの映像：{caps.actual[0]}×{caps.actual[1]}</p>}
        </>
      )}
      {msg && <p className="text-xs text-sub">{msg}</p>}
    </div>
  );
}
