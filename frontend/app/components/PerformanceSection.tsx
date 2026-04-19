"use client";

import { useEffect, useState } from "react";
import type { DriftAlert, PerformanceSummary } from "@/app/lib/api";
import { fetchPerformance } from "@/app/lib/api";

const TARGET_LABELS: Record<string, string> = {
  snowfall_24h: "24h Snowfall",
  wind_6h: "6h Wind",
  wind_12h: "12h Wind",
  freezing_level: "Freezing Level",
  precip_type: "Precip Type",
};

const TARGET_UNITS: Record<string, string> = {
  snowfall_24h: "cm",
  wind_6h: "km/h",
  wind_12h: "km/h",
  freezing_level: "m",
  precip_type: "%",
};

function MetricCard({
  target,
  location,
  rolling,
  baseline,
}: {
  target: string;
  location: string;
  rolling: { mae?: number | null; rmse?: number | null; accuracy?: number | null; n: number } | undefined;
  baseline: { mae?: number; accuracy?: number } | undefined;
}) {
  if (!rolling) return null;

  const isClassification = target === "precip_type";
  const liveValue = isClassification
    ? rolling.accuracy != null ? (rolling.accuracy * 100).toFixed(1) : "—"
    : rolling.mae != null ? rolling.mae.toFixed(1) : "—";
  const baselineValue = isClassification
    ? baseline?.accuracy != null ? (baseline.accuracy * 100).toFixed(1) : "—"
    : baseline?.mae != null ? baseline.mae.toFixed(1) : "—";
  const unit = TARGET_UNITS[target] || "";
  const label = isClassification ? "Acc" : "MAE";

  // Color: green if better than baseline, red if worse than 1.5x
  let color = "text-accent";
  if (!isClassification && rolling.mae != null && baseline?.mae != null) {
    const ratio = rolling.mae / baseline.mae;
    if (ratio > 1.5) color = "text-accent-red";
    else if (ratio > 1.0) color = "text-accent-orange";
    else color = "text-accent-green";
  } else if (isClassification && rolling.accuracy != null && baseline?.accuracy != null) {
    if (rolling.accuracy >= baseline.accuracy) color = "text-accent-green";
    else if (rolling.accuracy >= baseline.accuracy * 0.8) color = "text-accent-orange";
    else color = "text-accent-red";
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-1">
      <div className="text-[10px] text-muted uppercase tracking-wider">
        {TARGET_LABELS[target] || target} — {location}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`text-xl font-bold ${color}`}>{liveValue}</span>
        <span className="text-xs text-muted">{unit} {label}</span>
      </div>
      <div className="text-[10px] text-muted flex justify-between">
        <span>baseline: {baselineValue} {unit}</span>
        <span>n={rolling.n}</span>
      </div>
    </div>
  );
}

function DriftBanner({ alerts }: { alerts: DriftAlert[] }) {
  if (alerts.length === 0) return null;
  return (
    <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3">
      <div className="text-xs font-bold text-accent-red mb-1">DRIFT DETECTED</div>
      {alerts.map((a, i) => (
        <div key={i} className="text-xs text-accent-red/80">
          {TARGET_LABELS[a.target] || a.target} ({a.location}):
          {a.rolling_mae != null && ` MAE ${a.rolling_mae.toFixed(1)} vs baseline ${a.baseline_mae?.toFixed(1)} (${a.ratio}x)`}
          {a.rolling_accuracy != null && ` accuracy ${(a.rolling_accuracy * 100).toFixed(1)}% vs baseline ${((a.baseline_accuracy || 0) * 100).toFixed(1)}%`}
        </div>
      ))}
    </div>
  );
}

export default function PerformanceSection() {
  const [perf, setPerf] = useState<PerformanceSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPerformance()
      .then(setPerf)
      .catch(() => setPerf(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="text-xs text-muted">Loading performance metrics...</div>
      </div>
    );
  }

  if (!perf || Object.keys(perf.rolling_7d).length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="text-xs text-muted uppercase tracking-wider mb-2">Model Performance</div>
        <div className="text-sm text-muted">
          Collecting data... Predictions need 24h+ of observations to evaluate.
          Run the daily pipeline to start tracking performance.
        </div>
      </div>
    );
  }

  const targets = Object.keys(perf.rolling_7d);

  // System health: green if no drift, orange if some, red if many
  const healthStatus = perf.drift_alerts.length === 0 ? "ok" : perf.drift_alerts.length < 3 ? "degrading" : "drift";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted uppercase tracking-wider flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${
            healthStatus === "ok" ? "bg-accent-green" :
            healthStatus === "degrading" ? "bg-accent-orange" : "bg-accent-red"
          }`} />
          Live Model Performance — Rolling 7-Day
        </div>
      </div>

      <DriftBanner alerts={perf.drift_alerts} />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {targets.map((target) => {
          const locs = perf.rolling_7d[target];
          // Show alpine if available, else first location
          const locName = locs["alpine"] ? "alpine" : Object.keys(locs)[0];
          return (
            <MetricCard
              key={target}
              target={target}
              location={locName}
              rolling={locs[locName]}
              baseline={perf.baselines[target]}
            />
          );
        })}
      </div>
    </div>
  );
}
