import { createContext } from "react";

/** 一括プレビュー（低い fps）が、入っているか。ダッシュボードが決め、各タイルが見る */
export const BulkPreviewContext = createContext(false);
