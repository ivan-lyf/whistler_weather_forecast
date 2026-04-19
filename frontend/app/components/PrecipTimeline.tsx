"use client";

import type { Prediction } from "@/app/lib/api";

const TYPE_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  snow: { bg: "bg-accent/20", text: "text-accent", label: "SNOW" },
  rain: { bg: "bg-accent-orange/20", text: "text-accent-orange", label: "RAIN" },
  mixed: { bg: "bg-accent-green/20", text: "text-accent-green", label: "MIXED" },
  none: { bg: "bg-muted/10", text: "text-muted", label: "DRY" },
};

function formatHour(iso: string) {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}`;
}

export default function PrecipTimeline({ data }: { data: Prediction[] }) {
  const precip = data.filter((p) => p.target === "precip_type");

  if (precip.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Precipitation Type Timeline
        </div>
        <div className="text-sm text-muted">No precipitation type data available</div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-3 sm:p-4" role="img" aria-label="Precipitation type timeline">
      <div className="text-[10px] sm:text-xs text-muted uppercase tracking-wider mb-3">
        Precipitation Type Timeline
      </div>
      <div className="flex gap-0.5 overflow-x-auto pb-1" role="list" aria-label="Hourly precipitation types">
        {precip.map((p, i) => {
          const config = TYPE_COLORS[p.value as string] || TYPE_COLORS.mixed;
          return (
            <div
              key={i}
              role="listitem"
              className={`flex flex-col items-center justify-center min-w-[24px] sm:min-w-[28px] h-12 sm:h-14 rounded-sm ${config.bg}`}
              title={`${p.time}: ${p.value} (${((p.confidence || 0) * 100).toFixed(0)}%)`}
              aria-label={`${formatHour(p.time)}h: ${p.value}`}
            >
              <span className={`text-[8px] sm:text-[9px] font-bold ${config.text}`}>
                {(config.label || "").slice(0, 1)}
              </span>
              <span className="text-[7px] sm:text-[8px] text-muted">{formatHour(p.time)}</span>
            </div>
          );
        })}
      </div>
      <div className="flex gap-3 sm:gap-4 mt-2 text-[9px] sm:text-[10px] text-muted">
        {Object.entries(TYPE_COLORS).map(([key, cfg]) => (
          <div key={key} className="flex items-center gap-1">
            <div className={`w-2 h-2 rounded-full ${cfg.bg} border ${cfg.text.replace("text-", "border-")}`} aria-hidden="true" />
            {cfg.label}
          </div>
        ))}
      </div>
    </div>
  );
}
