"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { ForecastSummary, Prediction } from "@/app/lib/api";
import { fetchForecastSummary, fetchLatestPredictions } from "@/app/lib/api";
import AlertSubscribe from "./AlertSubscribe";
import ConditionsCard from "./ConditionsCard";
import PrecipTimeline from "./PrecipTimeline";
import SkierCard from "./SkierCard";

type Tab = "alpine" | "mid" | "base";

const TABS: { key: Tab; label: string; short: string }[] = [
  { key: "alpine", label: "Alpine 2200m", short: "Alpine" },
  { key: "mid", label: "Mid 1500m", short: "Mid" },
  { key: "base", label: "Base 675m", short: "Base" },
];

export default function SkierDashboard() {
  const [tab, setTab] = useState<Tab>("alpine");
  const [summary, setSummary] = useState<ForecastSummary | null>(null);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetchForecastSummary(tab),
      fetchLatestPredictions(tab),
    ])
      .then(([sum, preds]) => {
        setSummary(sum);
        setPredictions(preds);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab]);

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-4 py-4 sm:py-6 flex flex-col gap-4 sm:gap-5">
      {/* Elevation tabs */}
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-1 bg-surface border border-border rounded-lg p-1"
          role="tablist"
          aria-label="Elevation bands"
        >
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 sm:px-4 py-1.5 rounded text-[10px] sm:text-xs font-bold uppercase tracking-wider transition-colors ${
                tab === t.key ? "bg-accent/20 text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              <span className="hidden sm:inline">{t.label}</span>
              <span className="sm:hidden">{t.short}</span>
            </button>
          ))}
        </div>
        {summary?.last_updated && (
          <div className="text-[9px] sm:text-[10px] text-muted flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-accent-green" aria-hidden="true" />
            {new Date(summary.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} UTC
          </div>
        )}
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 text-muted text-sm py-12" role="status" aria-live="polite">
          <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" aria-hidden="true" />
          Loading forecast...
        </div>
      )}

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3 text-accent-red text-xs" role="alert">
          {error}. Is the backend running?
        </div>
      )}

      {!loading && !error && summary && (
        <>
          {/* Hero cards — the skier's main questions */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <SkierCard
              title="Snowfall"
              unit="cm"
              icon="❄"
              color="accent"
              rows={[
                { label: "Next 6h", value: summary.snowfall_6h },
                { label: "Next 12h", value: summary.snowfall_12h },
                { label: "Next 24h", value: summary.snowfall_24h },
              ]}
            />
            <SkierCard
              title="Temperature"
              unit="°C"
              icon="🌡"
              color={summary.temp_now !== null && summary.temp_now < 0 ? "accent" : "orange"}
              rows={[
                { label: "Now", value: summary.temp_now },
                { label: "24h High", value: summary.temp_high_24h },
                { label: "24h Low", value: summary.temp_low_24h },
              ]}
            />
          </div>

          {/* Conditions */}
          <ConditionsCard
            precipType={summary.precip_type}
            precipConfidence={summary.precip_confidence}
            freezingLevel={summary.freezing_level}
            windRisk={summary.wind_risk}
            windNow={summary.wind_now}
            windPeak={summary.wind_peak_6h}
          />

          {/* Compact precip timeline */}
          <PrecipTimeline data={predictions} />

          {/* Alerts */}
          <AlertSubscribe />

          {/* Link to detailed charts */}
          <Link
            href={`/details?location=${tab}`}
            className="flex items-center justify-center gap-2 bg-surface border border-border rounded-lg px-4 py-3 text-xs text-muted hover:text-accent hover:border-accent/30 transition-colors"
          >
            View hourly charts & detailed analysis
            <span aria-hidden="true">&rarr;</span>
          </Link>

          {/* Footer */}
          <footer className="text-[9px] sm:text-[10px] text-muted border-t border-border pt-3 flex flex-wrap gap-x-4 gap-y-1">
            <span>data: GFS + ECMWF ensemble</span>
            <span>model: LightGBM v1</span>
            <span>ML-corrected forecast</span>
          </footer>
        </>
      )}
    </div>
  );
}
