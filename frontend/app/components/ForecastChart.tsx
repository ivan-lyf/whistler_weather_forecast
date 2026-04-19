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
import { useThemeColors } from "@/app/lib/useThemeColors";

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
  const theme = useThemeColors();

  if (!data || data.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">{title}</div>
        <div className="flex items-center justify-center h-[200px] text-sm text-muted">
          No data available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-3 sm:p-4" role="img" aria-label={`${title} chart`}>
      <div className="text-[10px] sm:text-xs text-muted uppercase tracking-wider mb-3">{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 5, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${title.replace(/\s/g, "")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
          <XAxis
            dataKey="time"
            tickFormatter={(v) => formatHour(String(v))}
            tick={{ fill: theme.muted, fontSize: 9 }}
            stroke={theme.border}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: theme.muted, fontSize: 9 }}
            stroke={theme.border}
            width={35}
          />
          <Tooltip
            contentStyle={{
              background: theme.surface,
              border: `1px solid ${theme.border}`,
              borderRadius: 6,
              fontSize: 11,
              fontFamily: "monospace",
              color: theme.foreground,
            }}
            labelFormatter={(label) => formatHour(String(label))}
            formatter={(val) => [`${Number(val).toFixed(1)} ${unit}`, title]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            fill={`url(#grad-${title.replace(/\s/g, "")})`}
            strokeWidth={2}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
