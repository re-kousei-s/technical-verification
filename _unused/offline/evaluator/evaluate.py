"""集計：IN/OUT を正解と比べ、条件ごとの誤差と、エッジ系とサーバー系の差を出す。

入力
  outputs/counts/results.csv     … aggregator の出力
  data/ground_truth.csv          … 目視で数えた正解（video_id, gt_in, gt_out）
  data/frame_counts.csv          … （任意）サンプルフレームの人数（video_id, time_sec, gt_count）
  outputs/frame_counts/*/*.csv   … 検出側が出した、そのフレームの検出スコア
出力（outputs/report/）
  per_condition.csv  … 条件 × 動画ごとの誤差
  summary.csv        … 条件ごとに動画をまとめた誤差（主に見る表）
  edge_vs_server.csv … エッジ系の誤差が、基準のサーバー系と何ポイント違うか
  frame_recall.csv   … サンプルフレームでの検出数 / 正解人数
  fps_consistency.csv … 間引いた条件の通過イベントが、全フレーム（fps=0）の結果をどれだけ再現できたか
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

DATA = Path(os.environ.get("DATA_DIR", "/data"))
OUT = Path(os.environ.get("OUTPUTS_DIR", "/outputs"))
KEYS = ["pipeline", "model", "tiling", "sample_fps", "tracker", "anchor"]


def err_pct(pred, gt):
    """(予測 - 正解) / 正解 * 100。正解0のときは、予測も0なら0、そうでなければ NaN。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        e = (pred - gt) / gt * 100
    return np.where(gt == 0, np.where(pred == 0, 0.0, np.nan), e)


def per_condition(results, gt, pass_pct):
    df = results.merge(gt[["video_id", "gt_in", "gt_out"]], on="video_id", how="left")
    df["in_err_pct"] = err_pct(df["in"], df["gt_in"])
    df["out_err_pct"] = err_pct(df["out"], df["gt_out"])
    # (|ΔIN| + |ΔOUT|) / (正解IN + 正解OUT) * 100。向きごとの誤差が打ち消し合わない総合値
    abs_err = (df["in"] - df["gt_in"]).abs() + (df["out"] - df["gt_out"]).abs()
    gt_total = df["gt_in"] + df["gt_out"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["total_err_pct"] = np.where(gt_total > 0, abs_err / gt_total * 100, np.where(abs_err == 0, 0.0, np.nan))
    df["pass"] = ((df["in_err_pct"].abs() <= pass_pct) & (df["out_err_pct"].abs() <= pass_pct)).astype("boolean")
    df.loc[df["gt_in"].isna(), "pass"] = pd.NA
    return df.round(1)


def summarize(df):
    g = df.groupby(KEYS, dropna=False)
    s = g.agg(
        videos=("video_id", "nunique"),
        total_err_pct_mean=("total_err_pct", "mean"),
        total_err_pct_max=("total_err_pct", "max"),
        pass_rate=("pass", lambda x: x.astype("Float64").mean()),
        infer_ms_mean=("infer_ms_mean", "mean"),
        dets_per_frame=("dets_per_frame", "mean"),
    ).reset_index()
    return s.sort_values(["total_err_pct_mean", "pipeline", "model"]).round(2)


def edge_vs_server(df, ref, allow_pt):
    ref_df = df[(df["pipeline"] == ref["pipeline"]) & (df["model"] == ref["model"])]
    on = ["video_id", "sample_fps", "tracker", "anchor"] + ([] if "tiling" in ref else ["tiling"])
    if "tiling" in ref:
        ref_df = ref_df[ref_df["tiling"] == ref["tiling"]]
    ref_df = ref_df[on + ["in", "out", "total_err_pct"]].rename(
        columns={"in": "ref_in", "out": "ref_out", "total_err_pct": "ref_total_err_pct"})
    edge = df[df["pipeline"] == "edge"]
    m = edge.merge(ref_df, on=on, how="inner")
    m["diff_pt"] = (m["total_err_pct"] - m["ref_total_err_pct"]).round(1)
    m["within_allowance"] = m["diff_pt"] <= allow_pt
    cols = ["video_id", "model", "tiling", "sample_fps", "tracker", "anchor", "in", "out", "ref_in", "ref_out",
            "total_err_pct", "ref_total_err_pct", "diff_pt", "within_allowance"]
    return m[cols]


def frame_recall(score_th):
    gt_path = DATA / "frame_counts.csv"
    if not gt_path.exists():
        return None
    gt = pd.read_csv(gt_path)
    rows = []
    for path in sorted((OUT / "frame_counts").glob("*/*.csv")):
        pipeline, model, tiling = path.stem.split("__")
        det = pd.read_csv(path, dtype={"scores": str}).fillna({"scores": ""})
        det["n_det"] = det["scores"].map(lambda s: sum(float(x) >= score_th for x in s.split()))
        m = det.merge(gt, on=["video_id", "time_sec"])
        if m.empty:
            continue
        rows.append({
            "video_id": m["video_id"].iloc[0], "pipeline": pipeline, "model": model, "tiling": tiling,
            "frames": len(m), "gt_people": int(m["gt_count"].sum()), "detected": int(m["n_det"].sum()),
            # 過検出で1を超えないよう、フレームごとに min(検出, 正解) で数える
            "recall_approx": round(float(np.minimum(m["n_det"], m["gt_count"]).sum() / max(m["gt_count"].sum(), 1)), 3),
        })
    return pd.DataFrame(rows)


def match_events(ref, test, max_dt, max_dx):
    """同じ向きで、時刻と位置が近いイベントを1対1で対応付ける（近い順に貪欲に）。対応できた数を返す。"""
    pairs = []
    for i, r in ref.iterrows():
        for j, t in test.iterrows():
            if r["direction"] == t["direction"]:
                dt, dx = abs(r["video_t"] - t["video_t"]), abs(r["anchor_x"] - t["anchor_x"])
                if dt <= max_dt and dx <= max_dx:
                    pairs.append((dt / max_dt + dx / max_dx, i, j))
    used_r, used_t = set(), set()
    for _, i, j in sorted(pairs):
        if i not in used_r and j not in used_t:
            used_r.add(i)
            used_t.add(j)
    return len(used_r)


def fps_consistency(max_dt, max_dx, ref_tracker):
    """間引きによる取りこぼしを測る：同じ検出器・判定点で、基準トラッカーを「全フレーム」で回した
    通過イベントを基準に、間引いた条件（トラッカーは全種類）のイベントを照合する。
    検出器そのものの誤りは基準にも含まれるので、ここでは測れない（正解との比較で測る）。"""
    rows = []
    for ref_path in sorted((OUT / "counts" / "events").glob(f"*/*__fpsall__{ref_tracker}__*.csv")):
        video_id = ref_path.parent.name
        ref = pd.read_csv(ref_path)
        pattern = ref_path.name.replace("__fpsall__", "__fps*__").replace(f"__{ref_tracker}__", "__*__")
        for test_path in sorted(ref_path.parent.glob(pattern)):
            fps = test_path.name.split("__fps")[1].split("__")[0]
            if fps == "all":
                continue
            test = pd.read_csv(test_path)
            matched = match_events(ref, test, max_dt, max_dx)
            pipeline, model, tiling, _, tracker, anchor = test_path.stem.split("__")
            rows.append({
                "video_id": video_id, "pipeline": pipeline, "model": model, "tiling": tiling,
                "tracker": tracker, "anchor": anchor, "sample_fps": float(fps),
                "ref_events": len(ref), "events": len(test), "matched": matched,
                "recall_vs_full": round(matched / len(ref), 3) if len(ref) else np.nan,
                "extra": len(test) - matched,
            })
    return pd.DataFrame(rows)


def main():
    cfg = yaml.safe_load(open(os.environ.get("CONFIG", "/configs/matrix.yaml"), encoding="utf-8"))
    ev = cfg.get("evaluation", {})
    results = pd.read_csv(OUT / "counts" / "results.csv")
    gt_path = DATA / "ground_truth.csv"
    gt = pd.read_csv(gt_path, comment="#") if gt_path.exists() else pd.DataFrame(columns=["video_id", "gt_in", "gt_out"])
    gt = gt.dropna(subset=["gt_in", "gt_out"])
    missing = sorted(set(results["video_id"]) - set(gt["video_id"]))
    if missing:
        print(f"[warn] 正解が無い動画（誤差は空欄になる）: {missing}  → data/ground_truth.csv に追記してください")

    report = OUT / "report"
    report.mkdir(parents=True, exist_ok=True)
    df = per_condition(results, gt, ev.get("pass_error_pct", 20))
    df.to_csv(report / "per_condition.csv", index=False)
    summary = summarize(df)
    summary.to_csv(report / "summary.csv", index=False)
    evs = edge_vs_server(df, ev.get("reference", {"pipeline": "server", "model": "rfdetr_medium"}),
                         ev.get("edge_vs_server_pt", 10))
    evs.to_csv(report / "edge_vs_server.csv", index=False)
    fr = frame_recall(ev.get("frame_count_score", 0.4))
    if fr is not None:
        fr.to_csv(report / "frame_recall.csv", index=False)
    fc = fps_consistency(ev.get("match_max_seconds", 1.5), ev.get("match_max_px", 100),
                         ev.get("reference_tracker", "bytetrack"))
    if len(fc):
        fc.to_csv(report / "fps_consistency.csv", index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print("\n== 条件ごとの IN/OUT（動画別） ==")
    print(df[["video_id"] + KEYS + ["in", "out", "gt_in", "gt_out", "total_err_pct", "pass"]].to_string(index=False))
    print("\n== 条件ごとのまとめ（誤差の小さい順） ==")
    print(summary.to_string(index=False))
    if len(evs):
        print(f"\n== エッジ系 − 基準サーバー系 の誤差差（許容 {ev.get('edge_vs_server_pt', 10)} pt） ==")
        print(evs.to_string(index=False))
    if fr is not None and len(fr):
        print("\n== サンプルフレームでの検出率 ==")
        print(fr.to_string(index=False))
    if len(fc):
        print("\n== 間引きの影響：全フレーム基準の通過を何割再現できたか / 基準に無い通過の数（分割・動画をまとめた平均） ==")
        t = fc.pivot_table(index=["pipeline", "model", "tracker", "anchor"], columns="sample_fps",
                           values=["recall_vs_full", "extra"], aggfunc="mean").round(2)
        print(t.to_string())
    print(f"\n[done] {report}/ に CSV を出力しました")


if __name__ == "__main__":
    main()
