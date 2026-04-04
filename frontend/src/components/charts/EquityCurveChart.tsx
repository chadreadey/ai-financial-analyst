import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface EquityPoint {
  date: string;
  equity: number;
}

interface Props {
  data: EquityPoint[];
  height?: number;
}

export function EquityCurveChart({ data, height = 300 }: Props) {
  if (data.length === 0) return null;

  const isPositive = data[data.length - 1].equity >= data[0].equity;
  const color = isPositive ? "#10b981" : "#ef4444";
  const first = data[0].equity;
  const pctData = data.map((d) => ({
    ...d,
    pct: ((d.equity - first) / first) * 100,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={pctData}>
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.2} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#4b5a6e" }} />
        <YAxis
          tick={{ fontSize: 10, fill: "#4b5a6e" }}
          tickFormatter={(v: number) => `${v.toFixed(1)}%`}
        />
        <Tooltip
          contentStyle={{ background: "#111827", border: "1px solid #1e2d40", color: "#f0f4f8", fontSize: 12 }}
          formatter={(v: unknown) => [`${(v as number).toFixed(2)}%`, "Return"]}
        />
        <Area type="monotone" dataKey="pct" stroke={color} fill="url(#eqGrad)" strokeWidth={1.5} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
