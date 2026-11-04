import { useDialog } from "../components/ui/DialogProvider";
import { api } from "../api";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

/** 消す操作を、ここにまとめる（どれも、確認してから実行する） */
export default function SettingsPage() {
  const dialog = useDialog();
  const { refresh } = useOverview();
  const run = (msg: string, fn: () => Promise<unknown>) => async () => {
    if (!await dialog.confirm(msg)) return;
    try { await fn(); refresh(); dialog.alert("実行しました"); } catch (e) { dialog.alert((e as Error).message); }
  };
  const rows = [
    { title: "全フロアを 0 に戻す（閉場）", desc: "フロアの人数の概算を 0 にします。IN/OUT の履歴は残ります。",
      btn: "実行", fn: run("全フロアの人数を 0 に戻します。よろしいですか？", api.resetFloors) },
    { title: "IN/OUT の履歴を全部消す", desc: "通過の記録と、端末ごとの累計を消します。フロアの人数の概算は変わりません。",
      btn: "実行", fn: run("全端末の IN/OUT の履歴を消します。元には戻せません。", () => api.resetHistory({})) },
    { title: "全部リセット", desc: "フロアの人数と、IN/OUT の履歴を、すべて消します。",
      btn: "実行", fn: run("フロアの人数も履歴も、すべて消します。元には戻せません。", api.resetAll) },
  ];
  return (
    <>
      <PageHeader title="リセット" sub="端末ごと・フロアごとのリセットは、それぞれのページにあります" />
      <Card pad={false}>
        {rows.map((r) => (
          <div key={r.title} className="flex flex-wrap items-center gap-4 border-b border-line px-4 py-4 last:border-0">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{r.title}</div>
              <div className="text-sm text-sub">{r.desc}</div>
            </div>
            <Button variant="danger" onClick={r.fn}>{r.btn}</Button>
          </div>
        ))}
      </Card>
    </>
  );
}
