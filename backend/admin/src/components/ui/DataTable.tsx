import type { ReactNode } from "react";

export interface Column<T> { header: string; cell: (row: T) => ReactNode; align?: "right"; className?: (row: T) => string }

/** 表。行が無いときは、empty の文言を出す */
export function DataTable<T>({ columns, rows, empty, rowKey }: {
  columns: Column<T>[]; rows: T[]; empty: string; rowKey: (row: T, i: number) => string | number;
}) {
  if (!rows.length) return <div className="px-4 py-6 text-center text-sub">{empty}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-line text-xs text-sub">
            {columns.map((c) => (
              <th key={c.header} className={`whitespace-nowrap px-4 py-2 font-medium ${c.align === "right" ? "text-right" : "text-left"}`}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)} className="border-b border-line/60 last:border-0 hover:bg-bg">
              {columns.map((c) => (
                <td key={c.header} className={`whitespace-nowrap px-4 py-2 ${c.align === "right" ? "text-right tabular-nums" : ""} ${c.className?.(r) ?? ""}`}>{c.cell(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
