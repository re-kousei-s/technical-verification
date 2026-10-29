import { useState } from "react";
import { api } from "../api";
import { BulkPreviewContext } from "../components/camera/BulkPreviewContext";
import { CameraTile } from "../components/camera/CameraTile";
import { CrossingsTable } from "../components/CrossingsTable";
import { FloorSection } from "../components/floor/FloorSection";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { useOverview } from "../hooks/useOverview";

/**
 * 監視カメラの画面のような、メインの画面。フロアごとに、端末のタイルを並べる。
 *   未接続は「未接続」、接続中は「プレビューを見る」、認識中は現在の IN/OUT。
 * 上のボタンで、一括の認識開始・停止と、一括のプレビュー（低い fps）。タイルを押すと、端末のページへ。
 */
export default function DashboardPage() {
  const { data, refresh } = useOverview();
  const [bulkPreview, setBulkPreview] = useState(false);
  if (!data) return <p className="text-sub">読み込み中…</p>;

  const online = data.cameras.filter((c) => c.phone_online).length;
  const bulkRecognize = async (on: boolean) => {
    if (!confirm(on ? "スマホがつながっている全端末で、認識を開始します。" : "全端末の認識を停止します。")) return;
    try { await api.recognizeAll(on); refresh(); } catch (e) { alert((e as Error).message); }
  };
  const byId = new Map(data.cameras.map((c) => [c.id, c]));

  return (
    <BulkPreviewContext.Provider value={bulkPreview}>
      <PageHeader
        title="ダッシュボード" sub={`スマホ接続中 ${online} 台 ／ 全 ${data.cameras.length} 台。タイルを押すと、線の調整・リアルタイム表示・カメラの設定ができます`}
        actions={<>
          <Button variant={bulkPreview ? "outlined" : "filled"} onClick={() => setBulkPreview(!bulkPreview)}>
            {bulkPreview ? "一括プレビューを停止" : "一括プレビュー開始（低 fps）"}
          </Button>
          <Button variant="filled" onClick={() => bulkRecognize(true)}>一括認識開始</Button>
          <Button variant="danger" onClick={() => bulkRecognize(false)}>一括認識停止</Button>
        </>}
      />
      {data.floors.filter((f) => f.cameras.length).map((f) => (
        <FloorSection key={f.floor} floor={f}>
          {f.cameras.filter((c) => byId.has(c.id)).map((c) => <CameraTile key={c.id} cameraId={c.id} />)}
        </FloorSection>
      ))}
      {!data.cameras.length && <p className="text-sub">まだ端末が登録されていません。スマホで送信ページを開いて、登録してください。</p>}
      <div className="mt-8">
        <Card title="直近の通過" pad={false}><CrossingsTable limit={10} /></Card>
      </div>
    </BulkPreviewContext.Provider>
  );
}
