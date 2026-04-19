"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ComparisonPoint, Prediction } from "@/app/lib/api";
import {
  fetchComparison,
  fetchForecastCurrent,
  fetchLatestPredictions,
  fetchPredictions,
} from "@/app/lib/api";
import ComparisonChart from "@/app/components/ComparisonChart";
import ForecastChart from "@/app/components/ForecastChart";
import PerformanceSection from "@/app/components/PerformanceSection";

type Tab = "alpine" | "mid" | "base";

const TABS: { key: Tab; label: string }[] = [
  { key: "alpine", label: "Alpine 2200m" },
  { key: "mid", label: "Mid 1500m" },
  { key: "base", label: "Base 675m" },
];

const DEMO_START = "2025-11-25T00:00:00+00:00";
const DEMO_END = "2025-11-28T00:00:00+00:00";

export default function DetailsDashboard() {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("location") as Tab) || "alpine";

  const [tab, setTab] = useState<Tab>(initialTab);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [comparison, setComparison] = useState<ComparisonPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    fetchForecastCurrent()
      .then(async (info) => {
        if (info.status === "ok" && info.prediction_count && info.prediction_count > 0) {
          const preds = await fetchLatestPredictions(tab);
          if (preds.length > 0) {
            setPredictions(preds);
            const times = preds.map((p) => p.time).sort();
            const comp = await fetchComparison(times[0], times[times.length - 1], tab);
            setComparison(comp);
            return;
          }
        }
        const [preds, comp] = await Promise.all([
          fetchPredictions(DEMO_START, DEMO_END, tab),
          fetchComparison(DEMO_START, DEMO_END, tab),
        ]);
        setPredictions(preds);
        setComparison(comp);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab]);

  const filterTarget = (t: string) =>
    predictions
      .filter((p) => p.target === t && typeof p.value === "number")
      .map((p) => ({ time: p.time, value: p.value as number }));

  const snowData = filterTarget("snowfall_24h");
  const wind6hData = filterTarget("wind_6h");
  const wind12hData = filterTarget("wind_12h");
  const fzlData = filterTarget("freezing_level");
  const tempData = filterTarget("temperature");

  return (
    <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6 flex flex-col gap-4 sm:gap-5">
      {/* Nav */}
      <div className="flex items-center justify-between">
        <Link href="/" className="text-xs text-muted hover:text-accent transition-colors flex items-center gap-1">
          <span aria-hidden="true">&larr;</span> Back to forecast
        </Link>
        <div className="flex items-center gap-1 bg-surface border border-border rounded-lg p-1" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 rounded text-[10px] sm:text-xs font-bold uppercase tracking-wider transition-colors ${
                tab === t.key ? "bg-accent/20 text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 text-muted text-sm py-12" role="status">
          <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          Loading...
        </div>
      )}

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3 text-accent-red text-xs" role="alert">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <div className="text-xs text-muted uppercase tracking-wider">Hourly Forecast Charts</div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
            <ForecastChart data={snowData} title="24h Snowfall (cm)" unit="cm" color="#39bae6" />
            <ForecastChart data={tempData} title="Temperature (°C)" unit="°C" color="#ff8f40" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
            <ForecastChart data={wind6hData} title="6h Max Wind (km/h)" unit="km/h" color="#ff3333" />
            <ForecastChart data={fzlData} title="Freezing Level (m)" unit="m" color="#7fd962" />
          </div>

          <ForecastChart data={wind12hData} title="12h Max Wind (km/h)" unit="km/h" color="#ff8f40" height={180} />

          <ComparisonChart data={comparison} />

          <PerformanceSection />

          <footer className="text-[9px] text-muted border-t border-border pt-3">
            Detailed hourly data from Open-Meteo GFS + ECMWF ensemble, corrected by LightGBM models
          </footer>
        </>
      )}
    </div>
  );
}
