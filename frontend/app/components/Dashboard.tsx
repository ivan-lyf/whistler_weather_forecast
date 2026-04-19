"use client";

import { useEffect, useRef, useState } from "react";
import type { ComparisonPoint, Prediction } from "@/app/lib/api";
import { fetchComparison, fetchForecastCurrent, fetchLatestPredictions, fetchPredictions } from "@/app/lib/api";
import AlertSubscribe from "./AlertSubscribe";
import ComparisonChart from "./ComparisonChart";
import ForecastChart from "./ForecastChart";
import PerformanceSection from "./PerformanceSection";
import PrecipTimeline from "./PrecipTimeline";
import StatCard from "./StatCard";

type Tab = "alpine" | "mid" | "base";

const TABS: { key: Tab; label: string }[] = [
  { key: "alpine", label: "Alpine 2200m" },
  { key: "mid", label: "Mid 1500m" },
  { key: "base", label: "Base 675m" },
];

const DEMO_START = "2025-11-25T00:00:00+00:00";
const DEMO_END = "2025-11-28T00:00:00+00:00";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("alpine");
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [comparison, setComparison] = useState<ComparisonPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"live" | "demo">("live");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Cancel previous in-flight request on tab change
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    fetchForecastCurrent()
      .then(async (info) => {
        if (controller.signal.aborted) return;

        if (info.status === "ok" && info.prediction_count && info.prediction_count > 0) {
          setMode("live");
          setLastUpdated(info.run_at || null);
          const preds = await fetchLatestPredictions(tab);
          if (controller.signal.aborted) return;
          if (preds.length > 0) {
            setPredictions(preds);
            const times = preds.map((p) => p.time).sort();
            const comp = await fetchComparison(times[0], times[times.length - 1], tab);
            if (!controller.signal.aborted) setComparison(comp);
            return;
          }
        }
        // Fall back to demo
        if (controller.signal.aborted) return;
        setMode("demo");
        const [preds, comp] = await Promise.all([
          fetchPredictions(DEMO_START, DEMO_END, tab),
          fetchComparison(DEMO_START, DEMO_END, tab),
        ]);
        if (!controller.signal.aborted) {
          setPredictions(preds);
          setComparison(comp);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [tab]);

  // Derived data
  const snowData = predictions
    .filter((p) => p.target === "snowfall_24h" && typeof p.value === "number")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const wind6hData = predictions
    .filter((p) => p.target === "wind_6h" && typeof p.value === "number")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const wind12hData = predictions
    .filter((p) => p.target === "wind_12h" && typeof p.value === "number")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const fzlData = predictions
    .filter((p) => p.target === "freezing_level" && typeof p.value === "number")
    .map((p) => ({ time: p.time, value: p.value as number }));

  const latestSnow = snowData.length > 0 ? snowData[snowData.length - 1].value : 0;
  const maxWind = wind6hData.length > 0 ? Math.max(...wind6hData.map((d) => d.value)) : 0;
  const latestFzl = fzlData.length > 0 ? fzlData[fzlData.length - 1].value : 0;

  const precipCounts = predictions
    .filter((p) => p.target === "precip_type" && typeof p.value === "string")
    .reduce((acc, p) => {
      const v = p.value as string;
      acc[v] = (acc[v] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  const dominantPrecip = Object.entries(precipCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";

  const windWarning = maxWind > 50 ? "HIGH" : maxWind > 30 ? "MODERATE" : "LOW";
  const windColor = maxWind > 50 ? "red" : maxWind > 30 ? "orange" : "green";

  return (
    <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6 flex flex-col gap-4 sm:gap-6">
      {/* Tab bar */}
      <div
        className="flex items-center gap-1 bg-surface border border-border rounded-lg p-1 w-fit"
        role="tablist"
        aria-label="Elevation bands"
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            aria-controls={`panel-${t.key}`}
            onClick={() => setTab(t.key)}
            className={`px-3 sm:px-4 py-1.5 rounded text-[10px] sm:text-xs font-bold uppercase tracking-wider transition-colors ${
              tab === t.key
                ? "bg-accent/20 text-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div id={`panel-${tab}`} role="tabpanel" aria-label={`${tab} forecast data`}>
        {loading && (
          <div className="flex items-center gap-2 text-muted text-sm py-8" role="status" aria-live="polite">
            <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" aria-hidden="true" />
            Loading predictions...
          </div>
        )}

        {error && (
          <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3 text-accent-red text-xs" role="alert">
            Error: {error}. Make sure the backend is running on port 8000.
          </div>
        )}

        {!loading && !error && (
          <div className="flex flex-col gap-4 sm:gap-6">
            {/* Stat cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
              <StatCard label="24h Snowfall" value={latestSnow.toFixed(1)} unit="cm" color="accent" sublabel="ML-corrected" />
              <StatCard label="Wind Risk" value={windWarning} sublabel={`Peak: ${maxWind.toFixed(0)} km/h`} color={windColor} />
              <StatCard label="Freezing Level" value={Math.round(latestFzl)} unit="m" color="accent" sublabel="Estimated altitude" />
              <StatCard label="Precip Type" value={dominantPrecip.toUpperCase()} color={dominantPrecip === "snow" ? "accent" : dominantPrecip === "rain" ? "orange" : "green"} sublabel="Dominant type" />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
              <ForecastChart data={snowData} title="24h Snowfall (cm)" unit="cm" color="#39bae6" />
              <ForecastChart data={fzlData} title="Freezing Level (m)" unit="m" color="#7fd962" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
              <ForecastChart data={wind6hData} title="6h Max Wind (km/h)" unit="km/h" color="#ff8f40" />
              <ForecastChart data={wind12hData} title="12h Max Wind (km/h)" unit="km/h" color="#ff3333" />
            </div>

            <PrecipTimeline data={predictions} />
            <ComparisonChart data={comparison} />
            <PerformanceSection />
            <AlertSubscribe />

            {/* Footer */}
            <footer className="text-[9px] sm:text-[10px] text-muted border-t border-border pt-3 sm:pt-4 flex flex-wrap gap-x-4 sm:gap-x-6 gap-y-1">
              <span className="flex items-center gap-1">
                <span className={`w-1.5 h-1.5 rounded-full ${mode === "live" ? "bg-accent-green" : "bg-accent-orange"}`} aria-hidden="true" />
                {mode === "live" ? "LIVE" : "DEMO"}
              </span>
              <span>data: Open-Meteo GFS+ECMWF</span>
              <span>model: LightGBM v1 (5 targets)</span>
              {lastUpdated && <span>updated: {new Date(lastUpdated).toUTCString()}</span>}
              {mode === "demo" && <span>demo period: Nov 25-28, 2025</span>}
            </footer>
          </div>
        )}
      </div>
    </div>
  );
}
