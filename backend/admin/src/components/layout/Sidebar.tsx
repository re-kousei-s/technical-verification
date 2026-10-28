import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

// アイコンは、外部の部品を使わず、小さな SVG をそのまま書く
const icon = (d: string): ReactNode => (
  <svg viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);

const ITEMS: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
  { to: "/", label: "ダッシュボード", icon: icon("M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10"), end: true },
  { to: "/floors", label: "フロア", icon: icon("M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5") },
  { to: "/cameras", label: "端末", icon: icon("M4 7h3l2-3h6l2 3h3v13H4zM12 17a4 4 0 100-8 4 4 0 000 8z") },
  { to: "/crossings", label: "通過の履歴", icon: icon("M4 6h16M4 12h16M4 18h10") },
  { to: "/system", label: "システム", icon: icon("M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01") },
  { to: "/settings", label: "リセット", icon: icon("M4 12a8 8 0 108-8M4 4v5h5") },
];

/** 左のサイドバー（現在のページは、角丸の色つき帯で示す） */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-0.5 py-2 pr-3">
      {ITEMS.map((it) => (
        <NavLink
          key={it.to} to={it.to} end={it.end} onClick={onNavigate}
          className={({ isActive }) =>
            `flex h-11 items-center gap-4 rounded-r-full pl-6 pr-4 text-sm font-medium transition ${
              isActive ? "bg-primary-soft text-primary" : "text-ink hover:bg-ink/5"}`}
        >
          {it.icon}
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
