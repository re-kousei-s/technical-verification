import type { ReactNode } from "react";

/** 白いカード（Google の管理コンソールのような、薄い影の入れ物） */
export function Card({ title, action, children, className = "", pad = true }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface shadow-sm ${className}`}>
      {(title || action) && (
        <header className="flex items-center gap-3 border-b border-line px-4 py-3">
          <h2 className="text-[15px] font-medium text-ink">{title}</h2>
          <div className="ml-auto flex items-center gap-2">{action}</div>
        </header>
      )}
      <div className={pad ? "p-4" : ""}>{children}</div>
    </section>
  );
}
