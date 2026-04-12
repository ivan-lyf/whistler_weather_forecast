"use client";

import type { Prediction } from "@/app/lib/api";

const TYPE_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  snow: { bg: "bg-accent/20", text: "text-accent", label: "SNOW" },
  rain: { bg: "bg-accent-orange/20", text: "text-accent-orange", label: "RAIN" },
  mixed: { bg: "bg-accent-green/20", text: "text-accent-green", label: "MIXED" },
};

function formatHour(iso: string) {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}`;
}

export default function PrecipTimeline({ data }: { data: Prediction[] }) {
  const precip = data.filter((p) => p.target === "precip_type");

  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-muted uppercase tracking-wider mb-3">
        Precipitation Type Timeline
      </div>
      <div className="flex gap-0.5 overflow-x-auto">
        {precip.map((p, i) => {
          const config = TYPE_COLORS[p.value as string] || TYPE_COLORS.mixed;
          return (
            <div
              key={i}
              className={`flex flex-col items-center justify-center min-w-[28px] h-14 rounded-sm ${config.bg}`}
              title={`${p.time}: ${p.value} (${((p.confidence || 0) * 100).toFixed(0)}%)`}
            >
              <span className={`text-[9px] font-bold ${config.text}`}>
                {(config.label || "").slice(0, 1)}
              </span>
              <span className="text-[8px] text-muted">{formatHour(p.time)}</span>
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-2 text-[10px] text-muted">
        {Object.entries(TYPE_COLORS).map(([key, cfg]) => (
          <div key={key} className="flex items-center gap-1">
            <div className={`w-2 h-2 rounded-full ${cfg.bg} border ${cfg.text.replace("text-", "border-")}`} />
            {cfg.label}
          </div>
        ))}
      </div>
    </div>
  );
}
