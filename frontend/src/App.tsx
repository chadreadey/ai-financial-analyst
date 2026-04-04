import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { TopNav } from "./components/layout/TopNav";
import { AnalysisPage } from "./pages/AnalysisPage";
import { WatchlistPage } from "./pages/WatchlistPage";
import { NewsPage } from "./pages/NewsPage";
import { IndustryPage } from "./pages/IndustryPage";
import { StockDeepDivePage } from "./pages/StockDeepDivePage";
import { BacktestPage } from "./pages/BacktestPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
        <TopNav />
        <main className="max-w-7xl mx-auto px-4 py-6">
          <Routes>
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="/portfolio" element={<WatchlistPage />} />
            <Route path="/stock/:ticker" element={<StockDeepDivePage />} />
            <Route path="/news" element={<NewsPage />} />
            <Route path="/industry" element={<IndustryPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
            <Route path="/paper-trading" element={<PaperTradingPage />} />
            <Route path="*" element={<Navigate to="/analysis" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
