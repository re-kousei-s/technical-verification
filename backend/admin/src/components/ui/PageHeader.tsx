import type { ReactNode } from "react";

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-3">
      <div>
        <h1 className="text-[22px] font-normal text-ink">{title}</h1>
        {sub && <p className="mt-0.5 text-sm text-sub">{sub}</p>}
      </div>
      <div className="ml-auto flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}
