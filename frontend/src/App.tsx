import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { AnalysisPage } from "./pages/AnalysisPage";
import { StockDeepDivePage } from "./pages/StockDeepDivePage";
import { BacktestPage } from "./pages/BacktestPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/stock/:ticker" element={<StockDeepDivePage />} />
          <Route path="/backtest" element={<BacktestPage />} />
          <Route path="/paper-trading" element={<PaperTradingPage />} />
          <Route path="*" element={<Navigate to="/analysis" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}
