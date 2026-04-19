import { z } from "zod";

const API = process.env.NEXT_PUBLIC_API_URL;
if (!API) {
  throw new Error("NEXT_PUBLIC_API_URL is not set. Define it in .env.local (dev) or the hosting provider's env vars (prod).");
}

// ---------------------------------------------------------------------------
// Schemas (Zod validation for API responses)
// ---------------------------------------------------------------------------

const PredictionSchema = z.object({
  time: z.string(),
  target: z.string(),
  location: z.string(),
  value: z.union([z.number(), z.string(), z.null()]),
  unit: z.string(),
  confidence: z.number().nullable().optional(),
});

const ComparisonPointSchema = z.object({
  time: z.string(),
  raw_gfs_snowfall_cm: z.number().nullable(),
  corrected_snowfall_cm: z.number().nullable(),
  observed_snowfall_cm: z.number().nullable(),
});

const ForecastCurrentSchema = z.object({
  status: z.string(),
  message: z.string().nullable().optional(),
  run_at: z.string().nullable().optional(),
  fetched_at: z.string().nullable().optional(),
  prediction_count: z.number().nullable().optional(),
});

const DriftAlertSchema = z.object({
  target: z.string(),
  location: z.string(),
  rolling_mae: z.number().optional(),
  baseline_mae: z.number().optional(),
  ratio: z.number().optional(),
  rolling_accuracy: z.number().optional(),
  baseline_accuracy: z.number().optional(),
});

const RollingMetricSchema = z.record(
  z.string(),
  z.record(
    z.string(),
    z.object({
      mae: z.number().nullable().optional(),
      rmse: z.number().nullable().optional(),
      accuracy: z.number().nullable().optional(),
      n: z.number(),
      evaluated_at: z.string().nullable().optional(),
    })
  )
);

const PerformanceSummarySchema = z.object({
  rolling_7d: RollingMetricSchema,
  rolling_30d: RollingMetricSchema,
  baselines: z.record(z.string(), z.object({
    mae: z.number().optional(),
    accuracy: z.number().optional(),
  })),
  drift_alerts: z.array(DriftAlertSchema),
});

// ---------------------------------------------------------------------------
// Types (derived from schemas)
// ---------------------------------------------------------------------------

export type Prediction = z.infer<typeof PredictionSchema>;
export type ComparisonPoint = z.infer<typeof ComparisonPointSchema>;
export type ForecastCurrent = z.infer<typeof ForecastCurrentSchema>;
export type DriftAlert = z.infer<typeof DriftAlertSchema>;
export type PerformanceSummary = z.infer<typeof PerformanceSummarySchema>;

export interface TrendPoint {
  date: string;
  mae: number | null;
  rmse: number | null;
  accuracy: number | null;
  n: number;
}

// ---------------------------------------------------------------------------
// Cache (memoize API results per key)
// ---------------------------------------------------------------------------

const cache = new Map<string, { data: unknown; ts: number }>();
const CACHE_TTL_MS = 60_000; // 1 minute

function getCached<T>(key: string): T | null {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.ts < CACHE_TTL_MS) {
    return entry.data as T;
  }
  return null;
}

function setCache(key: string, data: unknown) {
  cache.set(key, { data, ts: Date.now() });
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function safeFetch<T>(url: string, schema: z.ZodType<T>, cacheKey?: string): Promise<T> {
  if (cacheKey) {
    const cached = getCached<T>(cacheKey);
    if (cached) return cached;
  }

  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
  }

  const json = await res.json();
  const parsed = schema.parse(json);

  if (cacheKey) setCache(cacheKey, parsed);
  return parsed;
}

async function safeFetchArray<T>(url: string, schema: z.ZodType<T>, cacheKey?: string): Promise<T[]> {
  if (cacheKey) {
    const cached = getCached<T[]>(cacheKey);
    if (cached) return cached;
  }

  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
  }

  const json = await res.json();
  const parsed = z.array(schema).parse(json);

  if (cacheKey) setCache(cacheKey, parsed);
  return parsed;
}

// Summary schema for skier hero page
const ForecastSummarySchema = z.object({
  location: z.string(),
  snowfall_6h: z.number().nullable(),
  snowfall_12h: z.number().nullable(),
  snowfall_24h: z.number().nullable(),
  temp_now: z.number().nullable(),
  temp_high_24h: z.number().nullable(),
  temp_low_24h: z.number().nullable(),
  wind_now: z.number().nullable(),
  wind_peak_6h: z.number().nullable(),
  wind_risk: z.string(),
  precip_type: z.string().nullable(),
  precip_confidence: z.number().nullable(),
  freezing_level: z.number().nullable(),
  last_updated: z.string().nullable(),
});

export type ForecastSummary = z.infer<typeof ForecastSummarySchema>;

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchPredictions(start: string, end: string, location: string): Promise<Prediction[]> {
  const key = `predictions:${start}:${end}:${location}`;
  return safeFetchArray(
    `${API}/api/predictions?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&location=${location}`,
    PredictionSchema, key,
  );
}

export async function fetchForecastSummary(location: string): Promise<ForecastSummary> {
  return safeFetch(`${API}/api/forecast/summary?location=${location}`, ForecastSummarySchema, `summary:${location}`);
}

export async function fetchLatestPredictions(location: string): Promise<Prediction[]> {
  const key = `predictions-latest:${location}`;
  return safeFetchArray(
    `${API}/api/predictions/latest?location=${location}`,
    PredictionSchema, key,
  );
}

export async function fetchForecastCurrent(): Promise<ForecastCurrent> {
  return safeFetch(`${API}/api/forecast/current`, ForecastCurrentSchema, "forecast-current");
}

export async function fetchComparison(start: string, end: string, location: string): Promise<ComparisonPoint[]> {
  const key = `comparison:${start}:${end}:${location}`;
  return safeFetchArray(
    `${API}/api/comparison?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&location=${location}`,
    ComparisonPointSchema, key,
  );
}

export async function fetchPerformance(): Promise<PerformanceSummary> {
  return safeFetch(`${API}/api/performance`, PerformanceSummarySchema, "performance");
}

export async function fetchPerformanceTrend(target: string, location: string, days: number = 30): Promise<TrendPoint[]> {
  const res = await fetch(`${API}/api/performance/trend?target=${target}&location=${location}&days=${days}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
