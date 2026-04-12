"use client";

import { useEffect, useState } from "react";
import type { ComparisonPoint, Prediction } from "@/app/lib/api";
import { fetchComparison, fetchPredictions } from "@/app/lib/api";
import ComparisonChart from "./ComparisonChart";
import ForecastChart from "./ForecastChart";
import MetricsTable from "./MetricsTable";
import PrecipTimeline from "./PrecipTimeline";
import StatCard from "./StatCard";

type Tab = "alpine" | "mid" | "base";

const DEMO_START = "2025-11-25T00:00:00+00:00";
const DEMO_END = "2025-11-28T00:00:00+00:00";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("alpine");
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [comparison, setComparison] = useState<ComparisonPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchPredictions(DEMO_START, DEMO_END, tab),
      fetchComparison(DEMO_START, DEMO_END, tab),
    ])
      .then(([preds, comp]) => {
        setPredictions(preds);
        setComparison(comp);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab]);

  const snowData = predictions
    .filter((p) => p.target === "snowfall_24h")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const wind6hData = predictions
    .filter((p) => p.target === "wind_6h")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const wind12hData = predictions
    .filter((p) => p.target === "wind_12h")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const fzlData = predictions
    .filter((p) => p.target === "freezing_level")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const latestSnow = snowData.length > 0 ? snowData[snowData.length - 1].value : 0;
  const maxWind = wind6hData.length > 0 ? Math.max(...wind6hData.map((d) => d.value)) : 0;
  const latestFzl = fzlData.length > 0 ? fzlData[fzlData.length - 1].value : 0;

  const precipCounts = predictions
    .filter((p) => p.target === "precip_type")
    .reduce((acc, p) => {
      const v = p.value as string;
      acc[v] = (acc[v] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  const dominantPrecip = Object.entries(precipCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";

  const windWarning = maxWind > 50 ? "HIGH" : maxWind > 30 ? "MODERATE" : "LOW";
  const windColor = maxWind > 50 ? "red" : maxWind > 30 ? "orange" : "green";

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 flex flex-col gap-6">
      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-surface border border-border rounded-lg p-1 w-fit">
        {(["alpine", "mid", "base"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded text-xs font-bold uppercase tracking-wider transition-colors ${
              tab === t
                ? "bg-accent/20 text-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            {t === "alpine" ? "Alpine 2200m" : t === "mid" ? "Mid 1500m" : "Base 675m"}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-muted text-sm">
          <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          Loading predictions...
        </div>
      )}

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3 text-accent-red text-xs">
          Error: {error}. Make sure the backend is running on port 8000.
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="24h Snowfall"
              value={latestSnow.toFixed(1)}
              unit="cm"
              color="accent"
              sublabel="ML-corrected prediction"
            />
            <StatCard
              label="Wind Risk"
              value={windWarning}
              sublabel={`Peak: ${maxWind.toFixed(0)} km/h`}
              color={windColor}
            />
            <StatCard
              label="Freezing Level"
              value={Math.round(latestFzl)}
              unit="m"
              color="accent"
              sublabel="Estimated altitude"
            />
            <StatCard
              label="Precip Type"
              value={dominantPrecip.toUpperCase()}
              color={dominantPrecip === "snow" ? "accent" : dominantPrecip === "rain" ? "orange" : "green"}
              sublabel="Dominant type"
            />
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ForecastChart data={snowData} title="24h Snowfall (cm)" unit="cm" color="#39bae6" />
            <ForecastChart data={fzlData} title="Freezing Level (m)" unit="m" color="#7fd962" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ForecastChart data={wind6hData} title="6h Max Wind (km/h)" unit="km/h" color="#ff8f40" />
            <ForecastChart data={wind12hData} title="12h Max Wind (km/h)" unit="km/h" color="#ff3333" />
          </div>

          {/* Precip timeline */}
          <PrecipTimeline data={predictions} />

          {/* Comparison chart */}
          <ComparisonChart data={comparison} />

          {/* Metrics table */}
          <MetricsTable />

          {/* Footer info */}
          <div className="text-[10px] text-muted border-t border-border pt-4 flex flex-wrap gap-x-6 gap-y-1">
            <span>data: Open-Meteo GFS + ECCC observations</span>
            <span>model: LightGBM correction (5 targets)</span>
            <span>train: 2022-2024 | test: 2025H2</span>
            <span>demo period: Nov 25-28, 2025</span>
          </div>
        </>
      )}
    </div>
  );
}
