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

function formatHour(iso: string) {
  const d = new Date(iso);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

export default function ComparisonChart({ data }: { data: ComparisonPoint[] }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-muted uppercase tracking-wider mb-3">
        24h Snowfall Comparison — Raw GFS vs Corrected vs Observed
      </div>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2530" />
          <XAxis
            dataKey="time"
            tickFormatter={formatHour}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            stroke="#1e2530"
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fill: "#6b7280", fontSize: 10 }} stroke="#1e2530" width={40} />
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
          />
          <Legend
            wrapperStyle={{ fontSize: 11, fontFamily: "monospace" }}
          />
          <Line
            type="monotone"
            dataKey="raw_gfs_snowfall_cm"
            stroke="#6b7280"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            dot={false}
            name="Raw GFS"
          />
          <Line
            type="monotone"
            dataKey="corrected_snowfall_cm"
            stroke="#39bae6"
            strokeWidth={2}
            dot={false}
            name="ML Corrected"
          />
          <Line
            type="monotone"
            dataKey="observed_snowfall_cm"
            stroke="#7fd962"
            strokeWidth={1.5}
            dot={false}
            name="Observed"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
