interface ConditionsCardProps {
  precipType: string | null;
  precipConfidence: number | null;
  freezingLevel: number | null;
  windRisk: string;
  windNow: number | null;
  windPeak: number | null;
}

const PRECIP_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  snow: { icon: "❄", color: "text-accent", label: "SNOW" },
  rain: { icon: "🌧", color: "text-accent-orange", label: "RAIN" },
  mixed: { icon: "🌨", color: "text-accent-green", label: "MIXED" },
  none: { icon: "☀", color: "text-muted", label: "DRY" },
};

const WIND_CONFIG: Record<string, { color: string }> = {
  LOW: { color: "text-accent-green" },
  MODERATE: { color: "text-accent-orange" },
  HIGH: { color: "text-accent-red" },
};

export default function ConditionsCard({
  precipType, precipConfidence, freezingLevel, windRisk, windNow, windPeak,
}: ConditionsCardProps) {
  const precip = PRECIP_CONFIG[precipType || ""] || { icon: "—", color: "text-muted", label: "N/A" };
  const wind = WIND_CONFIG[windRisk] || WIND_CONFIG.LOW;

  return (
    <div className="bg-surface border border-border rounded-lg p-4 sm:p-5 flex flex-col gap-4" role="status" aria-label="Current conditions">
      {/* Precip type — big hero */}
      <div className="flex items-center gap-3">
        <span className="text-3xl">{precip.icon}</span>
        <div>
          <div className={`text-xl sm:text-2xl font-bold ${precip.color}`}>{precip.label}</div>
          {precipConfidence && (
            <div className="text-[10px] text-muted">{(precipConfidence * 100).toFixed(0)}% confidence</div>
          )}
        </div>
      </div>

      {/* Wind + Freezing level */}
      <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div>
          <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Wind</div>
          <div className={`text-sm font-bold ${wind.color}`}>{windRisk}</div>
          <div className="text-[10px] text-muted">
            Now: {windNow?.toFixed(0) || "—"} km/h
            {windPeak && <> · Peak: {windPeak.toFixed(0)}</>}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Freezing Level</div>
          <div className="text-sm font-bold text-accent">{freezingLevel ? `${freezingLevel}m` : "—"}</div>
          <div className="text-[10px] text-muted">
            {freezingLevel && freezingLevel > 2200 ? "Above alpine" :
             freezingLevel && freezingLevel > 1500 ? "Above mid" :
             freezingLevel && freezingLevel > 675 ? "Above base" : "Below base"}
          </div>
        </div>
      </div>
    </div>
  );
}
