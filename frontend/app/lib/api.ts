const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Prediction {
  time: string;
  target: string;
  location: string;
  value: number | string;
  unit: string;
  confidence?: number;
}

export interface ComparisonPoint {
  time: string;
  raw_gfs_snowfall_cm: number | null;
  corrected_snowfall_cm: number | null;
  observed_snowfall_cm: number | null;
}

export interface MetricsSummary {
  [model: string]: {
    target?: string;
    splits?: {
      test?: { mae?: number; rmse?: number; accuracy?: number; n?: number };
    };
    baselines?: Record<string, { mae?: number; rmse?: number; accuracy?: number }>;
  };
}

export async function fetchPredictions(start: string, end: string, location: string): Promise<Prediction[]> {
  const res = await fetch(`${API}/api/predictions?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&location=${location}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchComparison(start: string, end: string, location: string): Promise<ComparisonPoint[]> {
  const res = await fetch(`${API}/api/comparison?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&location=${location}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchMetrics(): Promise<MetricsSummary> {
  const res = await fetch(`${API}/api/metrics`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchLocations(): Promise<{ name: string; elevation_m: number }[]> {
  const res = await fetch(`${API}/api/locations`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
