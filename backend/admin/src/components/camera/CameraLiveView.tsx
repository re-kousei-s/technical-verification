import { useEffect, useRef, useState } from "react";
import { useCameraLive, useDetectBoxes } from "../../hooks/useCameraLive";
import { useLineEditor } from "../../hooks/useLineEditor";
import { useCamera } from "../../hooks/useOverview";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { LineOverlay } from "./LineOverlay";

/**
 * 端末 ID を渡すだけで、ライブ映像・線・IN/OUT・検出枠・線の編集がそろった部品。
 *   <CameraLiveView cameraId="F2-789E" />
 * 「ライブを開始」を押している間だけ、その端末は高い fps で送る（ページを開いただけでは、送らない）。
 */
export function CameraLiveView({ cameraId }: { cameraId: string }) {
  const cam = useCamera(cameraId);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false); // ライブを見ているか。押すまでは、つながない（端末に高い fps を頼まない）
  const [showBoxes, setShowBoxes] = useState(true);
  const [box, setBox] = useState({ w: 0, h: 0 });

  const live = useCameraLive(cameraId, canvas, on);
  const editor = useLineEditor(cameraId);
  const result = useDetectBoxes(cameraId, showBoxes && !editor.draft);

  // 映像の表示サイズ（線の座標を px にするため）
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const ratio = live.size ? live.size.w / live.size.h : 16 / 9;
  const lines = editor.draft ?? live.info?.lines ?? [];
  const editable = cam?.source === "db";
  const tone = live.status.tone === "ok" ? "ok" : live.status.tone === "wait" ? "warn" : "bad";
  const stopLive = () => { editor.cancel(); setOn(false); };
  const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : wrap.current?.parentElement?.requestFullscreen());

  return (
    <div className="flex flex-col gap-3">
      {/* 上の操作列 */}
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={tone} dot>{live.status.text}</Chip>
        {on && live.info && (
          <span className="text-xs text-sub">
            要求 {live.info.requested_fps}fps ／ 受信 {live.info.rx_fps != null ? live.info.rx_fps.toFixed(1) : "–"}fps ／ 表示 {live.shownFps != null ? live.shownFps.toFixed(1) : "–"}fps
          </span>
        )}
        <span className="flex-1" />
        {!editor.draft && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-sub">
              <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} /> 認識結果（枠）を重ねる
            </label>
            {on
              ? <Button variant="outlined" onClick={stopLive}>ライブを停止</Button>
              : <Button variant="filled" onClick={() => setOn(true)}>ライブを開始</Button>}
            <Button variant="outlined" onClick={() => live.info && editor.start(live.info.lines)}
              disabled={!on || !live.info || !editable} title={!editable ? "yaml で固定した端末の線は、変えられません" : on ? "" : "ライブを開始すると、線を編集できます"}>
              線を編集
            </Button>
            <Button variant="outlined" onClick={fullscreen}>全画面</Button>
          </>
        )}
      </div>

      {/* 線の編集バー */}
      {editor.draft && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-primary-soft px-3 py-2">
          <b className="text-primary">線の編集</b>
          <Button onClick={editor.add}>＋ 線を足す</Button>
          <Button onClick={editor.remove} disabled={editor.draft.length < 2}>選んだ線を消す</Button>
          <input
            className="h-9 w-44 rounded-full border border-line bg-surface px-3 text-sm"
            value={editor.draft[editor.selected]?.name ?? ""} onChange={(e) => editor.rename(e.target.value)}
            placeholder="線の名前" aria-label="選んだ線の名前" maxLength={24}
          />
          <span className={`text-xs ${editor.message?.bad ? "text-bad" : "text-sub"}`}>
            {editor.message?.text ?? "端の○をドラッグで形を、線の上をドラッグで位置を動かします。入口の下に置いてください"}
          </span>
          <span className="flex-1" />
          <Button variant="filled" onClick={editor.save} disabled={editor.saving}>{editor.saving ? "保存中…" : "保存"}</Button>
          <Button variant="text" onClick={editor.cancel}>やめる</Button>
        </div>
      )}

      {/* 映像。映像の縦横比に合わせた箱の上に、canvas と SVG を重ねる */}
      <div className="flex justify-center rounded-lg bg-black">
        <div ref={wrap} className="relative" style={{ width: `min(100%, calc(75vh * ${ratio}))`, aspectRatio: String(ratio) }}>
          <canvas ref={canvas} className="absolute inset-0 h-full w-full" />
          {!live.size && (
            <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-white/70">
              {on ? live.status.text : (
                <div className="flex flex-col items-center gap-3">
                  <span>ライブは停止中です。開始すると、端末は高い fps（{live.info?.requested_fps ?? 15}fps）で送ります</span>
                  <Button variant="filled" onClick={() => setOn(true)}>ライブを開始</Button>
                </div>
              )}
            </div>
          )}
          {on && box.w > 0 && (
            <LineOverlay
              lines={lines} width={box.w} height={box.h}
              boxes={showBoxes && !result?.stale ? result?.boxes : undefined}
              edit={editor.draft ? { selected: editor.selected, onSelect: editor.setSelected, onChange: editor.setLine } : undefined}
            />
          )}
          {/* 左上：累計と、線ごとの IN/OUT（編集中は、線が見えにくくなるので出さない） */}
          {on && live.info && !editor.draft && (
            <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-black/55 px-2.5 py-1.5 text-xs font-bold text-white">
              <div className="text-sm">IN {live.info.in}　OUT {live.info.out}</div>
              {lines.length >= 2 && lines.map((l) => {
                const c = live.info!.line_counts[l.name] ?? { in: 0, out: 0 };
                return <div key={l.id} className="font-medium text-white/85">{l.name}　IN {c.in} / OUT {c.out}</div>;
              })}
            </div>
          )}
        </div>
      </div>
      <p className="text-xs text-sub">
        映像はサーバーを素通りし、このブラウザがデコードします。枠は認識の頻度でしか更新されないので、映像より遅れて動きます。
      </p>
    </div>
  );
}
