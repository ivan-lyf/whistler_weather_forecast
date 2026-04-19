"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ComparisonPoint } from "@/app/lib/api";
import { useThemeColors } from "@/app/lib/useThemeColors";

function formatHour(iso: string) {
  const d = new Date(iso);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

export default function ComparisonChart({ data }: { data: ComparisonPoint[] }) {
  const theme = useThemeColors();

  if (!data || data.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">24h Snowfall Comparison</div>
        <div className="flex items-center justify-center h-[200px] text-sm text-muted">No comparison data available</div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-3 sm:p-4" role="img" aria-label="Snowfall comparison chart">
      <div className="text-[10px] sm:text-xs text-muted uppercase tracking-wider mb-3">
        24h Snowfall — Raw GFS vs Corrected vs Observed
      </div>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={data} margin={{ top: 5, right: 5, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
          <XAxis
            dataKey="time"
            tickFormatter={(v) => formatHour(String(v))}
            tick={{ fill: theme.muted, fontSize: 9 }}
            stroke={theme.border}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fill: theme.muted, fontSize: 9 }} stroke={theme.border} width={35} />
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
          />
          <Legend wrapperStyle={{ fontSize: 10, fontFamily: "monospace" }} />
          <Line type="monotone" dataKey="raw_gfs_snowfall_cm" stroke={theme.muted}
                strokeWidth={1.5} strokeDasharray="4 4" dot={false} name="Raw GFS" />
          <Line type="monotone" dataKey="corrected_snowfall_cm" stroke="#39bae6"
                strokeWidth={2} dot={false} name="ML Corrected" />
          <Line type="monotone" dataKey="observed_snowfall_cm" stroke="#2d8a4e"
                strokeWidth={1.5} dot={false} name="Observed" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
