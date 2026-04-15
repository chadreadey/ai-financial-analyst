import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  AreaSeries,
  CrosshairMode,
  LineStyle,
  type IChartApi,
} from "lightweight-charts";
import type { PriceBar, RecommendationRecord } from "../../api/types";

interface ForecastBand {
  time: string;
  p10: number;
  p50: number;
  p90: number;
}

interface PriceChartProps {
  bars: PriceBar[];
  recommendations: RecommendationRecord[];
  forecast?: ForecastBand[];
  height?: number;
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function tsToDate(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

export function PriceChart({ bars, recommendations, forecast, height = 400 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    x: number;
    y: number;
    date: string;
    o: number;
    h: number;
    l: number;
    c: number;
  }>({ visible: false, x: 0, y: 0, date: "", o: 0, h: 0, l: 0, c: 0 });

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: { background: { color: "#0f0f11" }, textColor: "#71717a" },
      grid: { vertLines: { color: "#1a1a1e" }, horzLines: { color: "#1a1a1e" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1a1a1e" },
      timeScale: { borderColor: "#1a1a1e" },
    });
    chartRef.current = chart;

    const sorted = [...bars].sort((a, b) => a.time.localeCompare(b.time));

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candleSeries.setData(sorted);

    const markers: any[] = [];
    const verdictColors: Record<string, string> = {
      BUY: "#22c55e", "STRONG BUY": "#22c55e",
      SELL: "#ef4444", "STRONG SELL": "#ef4444",
      HOLD: "#fbbf24",
    };

    for (const rec of recommendations) {
      const date = typeof rec.run_at === "number" ? tsToDate(rec.run_at) : String(rec.run_at);
      const v = rec.verdict?.toUpperCase() || "";
      const color = verdictColors[v] || "#94a3b8";

      const isBuy = v.includes("BUY");
      const isSell = v.includes("SELL");

      markers.push({
        time: date,
        position: isSell ? "aboveBar" : "belowBar",
        color,
        shape: isBuy ? "arrowUp" : isSell ? "arrowDown" : "circle",
        text: rec.verdict || "",
      });

      if (rec.target_price != null) {
        const endDate = addDays(date, 90);
        const targetLine = chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        targetLine.setData([
          { time: date, value: rec.target_price },
          { time: endDate, value: rec.target_price },
        ]);
      }
    }

    if (markers.length > 0) {
      markers.sort((a, b) => a.time.localeCompare(b.time));
      createSeriesMarkers(candleSeries, markers);
    }

    if (forecast && forecast.length > 0) {
      const p90Series = chart.addSeries(AreaSeries, {
        topColor: "rgba(6,182,212,0.12)",
        bottomColor: "transparent",
        lineColor: "rgba(6,182,212,0.3)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      p90Series.setData(forecast.map((f) => ({ time: f.time, value: f.p90 })));

      const p10Series = chart.addSeries(AreaSeries, {
        topColor: "transparent",
        bottomColor: "rgba(6,182,212,0.08)",
        lineColor: "rgba(6,182,212,0.3)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      p10Series.setData(forecast.map((f) => ({ time: f.time, value: f.p10 })));

      const p50Line = chart.addSeries(LineSeries, {
        color: "#06b6d4",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      p50Line.setData(forecast.map((f) => ({ time: f.time, value: f.p50 })));
    }

    chart.subscribeCrosshairMove((param) => {
      if (!param.point || !param.time) {
        setTooltip((prev) => ({ ...prev, visible: false }));
        return;
      }
      const price = param.seriesData.get(candleSeries) as any;
      if (price) {
        setTooltip({
          visible: true,
          x: param.point.x,
          y: param.point.y,
          date: String(param.time),
          o: price.open,
          h: price.high,
          l: price.low,
          c: price.close,
        });
      }
    });

    chart.timeScale().fitContent();

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [bars, recommendations, forecast, height]);

  return (
    <div ref={containerRef} className="relative rounded" style={{ height }}>
      {tooltip.visible && (
        <div
          className="absolute z-10 pointer-events-none px-3 py-2 rounded text-xs"
          style={{
            left: Math.min(tooltip.x + 12, (containerRef.current?.clientWidth || 400) - 180),
            top: tooltip.y - 60,
            background: "rgba(15,15,17,0.95)",
            border: "1px solid #1a1a1e",
            color: "#f0f4f8",
          }}
        >
          <div className="font-medium mb-1">{tooltip.date}</div>
          <div>O: {tooltip.o.toFixed(2)} H: {tooltip.h.toFixed(2)}</div>
          <div>L: {tooltip.l.toFixed(2)} C: {tooltip.c.toFixed(2)}</div>
        </div>
      )}
    </div>
  );
}
