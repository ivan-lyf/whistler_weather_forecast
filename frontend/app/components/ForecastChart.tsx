"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface DataPoint {
  time: string;
  value: number;
}

interface ForecastChartProps {
  data: DataPoint[];
  title: string;
  unit: string;
  color?: string;
  height?: number;
}

function formatHour(iso: string) {
  const d = new Date(iso);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

export default function ForecastChart({
  data,
  title,
  unit,
  color = "#39bae6",
  height = 200,
}: ForecastChartProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-muted uppercase tracking-wider mb-3">{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${title}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2530" />
          <XAxis
            dataKey="time"
            tickFormatter={formatHour}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            stroke="#1e2530"
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 10 }}
            stroke="#1e2530"
            width={40}
          />
          <Tooltip
            contentStyle={{
              background: "#0d1117",
              border: "1px solid #1e2530",
              borderRadius: 6,
              fontSize: 12,
              fontFamily: "monospace",
              color: "#c5cbd3",
            }}
            labelFormatter={(label) => formatHour(String(label))}
            formatter={(val) => [`${Number(val).toFixed(1)} ${unit}`, title]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            fill={`url(#grad-${title})`}
            strokeWidth={2}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
