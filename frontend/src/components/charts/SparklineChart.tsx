import { LineChart, Line, Area, ResponsiveContainer } from "recharts";

interface Props {
  closes: number[];
  isPositive: boolean;
  height?: number;
}

export function SparklineChart({ closes, isPositive, height = 40 }: Props) {
  const color = isPositive ? "#06b6d4" : "#ef4444";
  const data = closes.map((v, i) => ({ v, i }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <defs>
          <linearGradient id={`spark-${isPositive ? "up" : "dn"}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.15} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          fill={`url(#spark-${isPositive ? "up" : "dn"})`}
          stroke="none"
        />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
