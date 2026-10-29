import { useCallback, useState } from "react";
import { api } from "../api";
import { MAX_LINES, newLine, type Pt } from "../lib/lines";
import type { Line } from "../types";

/**
 * 端末 1 台の線の編集。draft（編集中の線）が null のときは、編集していない。
 * 座標は 0〜1 の割合。保存すると、端末の設定に反映され、認識側は数秒で切り替わる。
 */
export function useLineEditor(cameraId: string, onSaved?: () => void) {
  const [draft, setDraft] = useState<Line[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  const start = useCallback((lines: Line[]) => {
    setDraft(JSON.parse(JSON.stringify(lines)));
    setSelected(0);
    setMessage(null);
  }, []);
  const cancel = useCallback(() => { setDraft(null); setMessage(null); }, []);

  const setLine = useCallback((i: number, pts: Pt[]) => {
    setDraft((d) => d && d.map((l, k) => (k === i ? { ...l, line: pts } : l)));
  }, []);

  const add = useCallback(() => {
    if (!draft) return;
    if (draft.length >= MAX_LINES) return setMessage({ text: `線は ${MAX_LINES} 本までです`, bad: true });
    setDraft([...draft, newLine(draft)]);
    setSelected(draft.length);
    setMessage({ text: "足しました。入口の下に動かしてください", bad: false });
  }, [draft]);

  const remove = useCallback(() => {
    if (!draft) return;
    if (draft.length < 2) return setMessage({ text: "線は最低 1 本必要です", bad: true });
    setDraft(draft.filter((_, k) => k !== selected));
    setSelected(Math.max(0, Math.min(selected, draft.length - 2)));
  }, [draft, selected]);

  // 始点と終点を入れ替える。IN の向き（始点→終点に対して左側）が、反対になる
  const flip = useCallback(() => {
    setDraft((d) => d && d.map((l, k) => (k === selected ? { ...l, line: [l.line[1], l.line[0]] } : l)));
  }, [selected]);

  const rename = useCallback((name: string) => {
    setDraft((d) => d && d.map((l, k) => (k === selected ? { ...l, name } : l)));
  }, [selected]);

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.saveLines(cameraId, draft);
      setDraft(null);
      setMessage(null);
      onSaved?.();
    } catch (e) {
      setMessage({ text: (e as Error).message, bad: true });
    } finally {
      setSaving(false);
    }
  }, [cameraId, draft, onSaved]);

  return { draft, selected, setSelected, message, saving, start, cancel, setLine, add, remove, flip, rename, save };
}
