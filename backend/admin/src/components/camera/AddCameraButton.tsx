import { useState } from "react";
import { api } from "../../api";
import { useOverview } from "../../hooks/useOverview";
import { Button } from "../ui/Button";
import { useDialog } from "../ui/DialogProvider";

/** 端末を追加するボタン。端末の追加は、管理画面だけができる（スマホは、追加された端末の一覧から、選ぶだけ） */
export function AddCameraButton() {
  const { refresh } = useOverview();
  const dialog = useDialog();
  const [open, setOpen] = useState(false);
  const [floor, setFloor] = useState("1");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const f = parseInt(floor, 10);
    if (Number.isNaN(f)) return dialog.alert("フロアは、整数で入力してください");
    setBusy(true);
    try {
      const cam = await api.addCamera(f, name.trim());
      refresh();
      setOpen(false);
      setName("");
      dialog.alert(`端末を追加しました（ID: ${cam.id}）。\nスマホで送信ページ（アプリ）を開き、一覧から、この端末を選んでください。`);
    } catch (e) {
      dialog.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const input = "mt-1 h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm";
  return (
    <>
      <Button variant="filled" onClick={() => setOpen(true)}>＋ 端末を追加</Button>
      {open && (
        <div className="fixed inset-0 z-[100] grid place-items-center bg-black/50 p-4" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-xl bg-surface p-5 shadow-card">
            <h2 className="text-base font-medium">端末を追加</h2>
            <label className="mt-4 block text-xs text-sub">フロア（階）
              <input className={input} type="number" inputMode="numeric" value={floor} onChange={(e) => setFloor(e.target.value)} autoFocus />
            </label>
            <label className="mt-3 block text-xs text-sub">端末の名前（任意）
              <input className={input} value={name} maxLength={30} placeholder="例: 階段A 上り口" onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()} />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="text" onClick={() => setOpen(false)}>やめる</Button>
              <Button variant="filled" onClick={submit} disabled={busy}>{busy ? "追加中…" : "追加する"}</Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
