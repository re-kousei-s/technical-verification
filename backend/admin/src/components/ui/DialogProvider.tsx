import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";

// ブラウザの confirm / prompt / alert は、埋め込みの画面（VS Code の簡易ブラウザなど）で、使えないことがある。
// 使えないと、ボタンを押しても、何も起きない。そのため、画面の中に出す確認の画面を使う。

interface Dialog {
  confirm: (message: string) => Promise<boolean>;
  prompt: (message: string, initial?: string) => Promise<string | null>;
  alert: (message: string) => Promise<void>;
}

const DialogContext = createContext<Dialog>({
  confirm: async () => false, prompt: async () => null, alert: async () => {},
});

export const useDialog = () => useContext(DialogContext);

type Pending =
  | { kind: "confirm"; message: string; resolve: (v: boolean) => void }
  | { kind: "prompt"; message: string; initial: string; resolve: (v: string | null) => void }
  | { kind: "alert"; message: string; resolve: () => void };

export function DialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [text, setText] = useState("");
  const queue = useRef<Promise<unknown>>(Promise.resolve()); // 同時に 2 つ出さない（順番に出す）

  const open = useCallback(<T,>(make: (resolve: (v: T) => void) => Pending): Promise<T> => {
    const run = () => new Promise<T>((resolve) => {
      const p = make((v) => { setPending(null); resolve(v); });
      if (p.kind === "prompt") setText(p.initial);
      setPending(p);
    });
    const next = queue.current.then(run, run);
    queue.current = next;
    return next;
  }, []);

  const api: Dialog = {
    confirm: (message) => open<boolean>((resolve) => ({ kind: "confirm", message, resolve })),
    prompt: (message, initial = "") => open<string | null>((resolve) => ({ kind: "prompt", message, initial, resolve })),
    alert: (message) => open<void>((resolve) => ({ kind: "alert", message, resolve })),
  };

  const cancel = () => {
    if (!pending) return;
    if (pending.kind === "confirm") pending.resolve(false);
    else if (pending.kind === "prompt") pending.resolve(null);
    else pending.resolve();
  };
  const ok = () => {
    if (!pending) return;
    if (pending.kind === "confirm") pending.resolve(true);
    else if (pending.kind === "prompt") pending.resolve(text);
    else pending.resolve();
  };

  return (
    <DialogContext.Provider value={api}>
      {children}
      {pending && (
        <div className="fixed inset-0 z-[100] grid place-items-center bg-black/50 p-4"
          onKeyDown={(e) => { if (e.key === "Escape") cancel(); }}>
          <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-xl bg-surface p-5 shadow-card">
            <p className="whitespace-pre-line text-sm text-ink">{pending.message}</p>
            {pending.kind === "prompt" && (
              <input autoFocus value={text} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") ok(); }}
                className="mt-3 h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm" />
            )}
            <div className="mt-5 flex justify-end gap-2">
              {pending.kind !== "alert" && <Button variant="text" onClick={cancel}>やめる</Button>}
              <Button variant="filled" autoFocus={pending.kind !== "prompt"} onClick={ok}>
                {pending.kind === "confirm" ? "実行する" : "OK"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  );
}
