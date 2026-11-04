import { HashRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { DialogProvider } from "./components/ui/DialogProvider";
import { OverviewProvider } from "./hooks/useOverview";
import CameraDetailPage from "./pages/CameraDetailPage";
import CamerasPage from "./pages/CamerasPage";
import CrossingsPage from "./pages/CrossingsPage";
import DashboardPage from "./pages/DashboardPage";
import FloorsPage from "./pages/FloorsPage";
import SettingsPage from "./pages/SettingsPage";
import SystemPage from "./pages/SystemPage";

// ページの切り替えは、URL の # 以降で行う（サーバー側に、ページごとの入口を作らなくてよい）
export default function App() {
  return (
    <DialogProvider>
    <OverviewProvider>
      <HashRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/floors" element={<FloorsPage />} />
            <Route path="/cameras" element={<CamerasPage />} />
            <Route path="/cameras/:id" element={<CameraDetailPage />} />
            <Route path="/crossings" element={<CrossingsPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </AppShell>
      </HashRouter>
    </OverviewProvider>
    </DialogProvider>
  );
}
