import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useLiveInfo } from "../../hooks/useLiveInfo";
import { useCamera } from "../../hooks/useOverview";

/**
 * 端末 ID の、スマホのカメラの設定（カメラの選択・解像度・ズーム）。管理画面で決めると、スマホが従う。
 * 選べる内容は、スマホが報告したもの（スマホの送信ページが開いている間だけ）。
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
  if (!caps) return <p className="text-sm text-sub">{info?.phone_online ? "スマホからの報告を待っています（届かないときは、スマホの送信ページを開き直してください）。" : "スマホが接続していません。スマホで送信ページを開くと、設定できます。"}</p>;

  const send = async (body: { res?: string; zoom?: number; device_id?: string }) => {
    try { await api.setCameraSettings(cameraId, body); setMsg("送りました。スマホが映像を取り直します"); }
    catch (e) { setMsg((e as Error).message); }
  };
  const select = "h-9 w-full rounded-lg border border-line bg-surface px-2 text-sm";
  return (
    <div className="space-y-3 text-sm">
      <label className="block">
        <span className="text-xs text-sub">カメラ（広角レンズなど）</span>
        <select className={select} value={caps.device_id} onChange={(e) => send({ device_id: e.target.value })}>
          {caps.devices.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-sub">解像度・縦横比</span>
        <select className={select} value={caps.res} onChange={(e) => send({ res: e.target.value })}>
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
      {msg && <p className="text-xs text-sub">{msg}</p>}
    </div>
  );
}
