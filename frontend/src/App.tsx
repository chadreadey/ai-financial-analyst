import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { AnalysisPage } from "./pages/AnalysisPage";
import { StockDeepDivePage } from "./pages/StockDeepDivePage";
import { BacktestPage } from "./pages/BacktestPage";
import { ModalRunDetailPage } from "./pages/ModalRunDetailPage";
import { ModalComboDetailPage } from "./pages/ModalComboDetailPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/stock/:ticker" element={<StockDeepDivePage />} />
          <Route path="/backtest" element={<BacktestPage />} />
          <Route
            path="/backtest/modal/runs/:runId"
            element={<ModalRunDetailPage />}
          />
          <Route
            path="/backtest/modal/runs/:runId/combos/:comboIdx"
            element={<ModalComboDetailPage />}
          />
          <Route path="/paper-trading" element={<PaperTradingPage />} />
          <Route path="*" element={<Navigate to="/analysis" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}
