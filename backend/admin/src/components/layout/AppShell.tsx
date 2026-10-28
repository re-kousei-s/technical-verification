import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Chip } from "../ui/Chip";
import { useOverview } from "../../hooks/useOverview";

/** 上のバー + 左のサイドバー + 本文。狭い画面では、サイドバーはメニューボタンで開く */
export function AppShell({ children }: { children: ReactNode }) {
  const { data, error } = useOverview();
  const [open, setOpen] = useState(false);
  const s = data?.services;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <button className="rounded-full p-2 hover:bg-ink/5 lg:hidden" aria-label="メニュー" onClick={() => setOpen(!open)}>
          <svg viewBox="0 0 24 24" className="h-6 w-6 fill-none stroke-current" strokeWidth="2" strokeLinecap="round"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm font-bold text-white">人</span>
          <span className="text-[19px] text-sub">人検出 <span className="text-ink">管理コンソール</span></span>
        </div>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          {s ? (
            <>
              <Chip tone={s.ingest ? "ok" : "bad"} dot>ingest</Chip>
              <Chip tone={s.redis ? "ok" : "bad"} dot>Redis</Chip>
              <Chip tone={s.postgres ? "ok" : "bad"} dot>Postgres</Chip>
              <Chip tone={s.workers_alive > 0 ? "ok" : "bad"} dot>worker {s.workers_alive}/{s.workers_total}</Chip>
            </>
          ) : <Chip>読み込み中…</Chip>}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* 広い画面では常に表示、狭い画面では開いたときだけ重ねて表示 */}
        <aside className={`${open ? "block" : "hidden"} absolute inset-x-0 bottom-0 top-16 z-30 bg-surface lg:static lg:block lg:w-64 lg:shrink-0 lg:border-r lg:border-line`}>
          <Sidebar onNavigate={() => setOpen(false)} />
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto">
          {(error || data?.problems.length) ? (
            <div className="border-b border-bad/30 bg-bad-soft px-6 py-2 text-sm text-bad">
              {error && <div>{error}</div>}
              {data?.problems.map((p) => <div key={p}>{p}</div>)}
            </div>
          ) : null}
          <div className="mx-auto max-w-[1360px] p-4 md:p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
