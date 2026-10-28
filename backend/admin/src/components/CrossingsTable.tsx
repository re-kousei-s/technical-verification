import { useEffect, useState } from "react";
import { api } from "../api";
import { clock } from "../lib/format";
import type { Crossing } from "../types";
import { DataTable } from "./ui/DataTable";

/** 通過の記録の表。cameraId を渡すとその端末だけ、省略すると全端末 */
export function CrossingsTable({ cameraId, limit = 50 }: { cameraId?: string; limit?: number }) {
  const [rows, setRows] = useState<Crossing[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => api.crossings(cameraId, limit).then((r) => alive && setRows(r)).catch(() => {});
    load();
    const t = window.setInterval(load, 3000);
    return () => { alive = false; window.clearInterval(t); };
  }, [cameraId, limit]);

  return (
    <DataTable
      rows={rows} rowKey={(r) => r.id} empty="まだ通過がありません"
      columns={[
        { header: "時刻", cell: (r) => clock(r.ts) },
        ...(cameraId ? [] : [{ header: "端末", cell: (r: Crossing) => r.camera_id }]),
        { header: "階", cell: (r) => r.floor ?? "–" },
        { header: "どの線", cell: (r) => r.line_name || "–" },
        { header: "向き", cell: (r) => r.direction.toUpperCase(), className: (r) => (r.direction === "in" ? "font-medium text-good" : "font-medium text-bad") },
        { header: "追跡ID", align: "right", cell: (r) => r.track_id },
      ]}
    />
  );
}
