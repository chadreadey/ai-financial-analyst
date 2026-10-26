import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { PublicLayout } from "./components/layout/PublicLayout";
import { HomePage } from "./pages/HomePage";
import { BriefPage } from "./pages/BriefPage";
import { LiveRunPage } from "./pages/LiveRunPage";
import { EvidencePage } from "./pages/EvidencePage";
import { LabGatePage } from "./pages/LabGatePage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { StockDeepDivePage } from "./pages/StockDeepDivePage";
import { BacktestPage } from "./pages/BacktestPage";
import { ModalRunDetailPage } from "./pages/ModalRunDetailPage";
import { ModalComboDetailPage } from "./pages/ModalComboDetailPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";

function LabLayout() {
  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}

function ToLabTicker({ base }: { base: "stock" | "deepdive" }) {
  const { ticker } = useParams();
  return <Navigate to={`/lab/${base}/${ticker}`} replace />;
}

function ToLabRun() {
  const { runId } = useParams();
  return <Navigate to={`/lab/backtest/modal/runs/${runId}`} replace />;
}

function ToLabCombo() {
  const { runId, comboIdx } = useParams();
  return <Navigate to={`/lab/backtest/modal/runs/${runId}/combos/${comboIdx}`} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<PublicLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/brief/:ticker" element={<BriefPage />} />
          <Route path="/run" element={<LiveRunPage />} />
          <Route path="/evidence" element={<EvidencePage />} />
        </Route>

        <Route path="/lab" element={<LabGatePage />} />
        <Route path="/lab" element={<LabLayout />}>
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="stock/:ticker" element={<StockDeepDivePage />} />
          <Route path="deepdive/:ticker" element={<StockDeepDivePage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="backtest/modal/runs/:runId" element={<ModalRunDetailPage />} />
          <Route
            path="backtest/modal/runs/:runId/combos/:comboIdx"
            element={<ModalComboDetailPage />}
          />
          <Route path="paper-trading" element={<PaperTradingPage />} />
          <Route path="*" element={<Navigate to="/lab" replace />} />
        </Route>

        {/* Legacy paths */}
        <Route path="/analysis" element={<Navigate to="/" replace />} />
        <Route path="/backtest" element={<Navigate to="/lab/backtest" replace />} />
        <Route path="/backtest/modal/runs/:runId" element={<ToLabRun />} />
        <Route path="/backtest/modal/runs/:runId/combos/:comboIdx" element={<ToLabCombo />} />
        <Route path="/paper-trading" element={<Navigate to="/lab/paper-trading" replace />} />
        <Route path="/stock/:ticker" element={<ToLabTicker base="stock" />} />
        <Route path="/deepdive/:ticker" element={<ToLabTicker base="deepdive" />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
