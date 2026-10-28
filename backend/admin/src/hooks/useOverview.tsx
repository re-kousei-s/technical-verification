import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Camera, Overview } from "../types";

interface Ctx {
  data: Overview | null;
  error: string | null;
  refresh: () => void;
}

const OverviewContext = createContext<Ctx>({ data: null, error: null, refresh: () => {} });

/** 一覧のデータを 2 秒ごとに読み、全ページで共有する（ページごとに読みに行かない） */
export function OverviewProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>();
  const fails = useRef(0);

  const load = useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      setData(await api.overview());
      setError(null);
      fails.current = 0;
    } catch (e) {
      fails.current++;
      setError(`管理サーバーに接続できません（${fails.current}回目）`);
    }
    timer.current = window.setTimeout(load, 2000);
  }, []);

  useEffect(() => {
    load();
    return () => window.clearTimeout(timer.current);
  }, [load]);

  return <OverviewContext.Provider value={{ data, error, refresh: load }}>{children}</OverviewContext.Provider>;
}

export const useOverview = () => useContext(OverviewContext);

/** 端末 ID から、その端末の一覧情報を取る */
export function useCamera(id: string | undefined): Camera | undefined {
  return useOverview().data?.cameras.find((c) => c.id === id);
}
