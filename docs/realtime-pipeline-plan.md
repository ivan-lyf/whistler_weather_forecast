# Real-Time Pipeline Plan

## Current State

The app currently runs on **historical data only**:
- Observations: 2022-01-01 to 2026-04-11 (ingested from ECCC + Open-Meteo archive)
- Forecasts: 2022-01-01 to 2026-04-10 (ingested from Open-Meteo Historical Forecast API)
- Models trained on 2022-2024, tested on 2025 H2
- Dashboard shows demo period (Nov 2025)

## Goal

Switch from historical-only to **live daily updates** so the dashboard shows:
- **Today's corrected forecast** for the next 48h
- **Real-time observations** updated hourly
- **Rolling model performance** tracked against actual outcomes

---

## Architecture Changes

### 1. Live Forecast Ingestion (NEW)

**Problem**: The Historical Forecast API provides past forecasts. For live predictions, we need the **current GFS forecast** (what GFS predicts will happen in the next 7-16 days).

**Solution**: Use the Open-Meteo **Forecast API** (not Historical):
- Endpoint: `https://api.open-meteo.com/v1/forecast`
- Returns: next 7-16 days of hourly forecasts from the latest GFS run
- Same variables as historical: temperature, precip, snowfall, wind, freezing level, etc.
- Free tier, no API key needed

**New script**: `scripts/ingest_live_forecast.py`
- Fetch latest GFS forecast for all 3 locations (base, mid, alpine)
- Store as a new `ForecastRun` with `run_at` = current GFS initialization time
- The `run_at` comes from the API response metadata (GFS runs at 00, 06, 12, 18 UTC)
- `lead_hours` = hours between `run_at` and `valid_at` (0 to 384)
- Idempotent: ON CONFLICT DO NOTHING on the existing unique index

**Key difference from historical**: Real lead_hours (0-384) instead of the synthetic 0-23 used in the archive backfill. The ML model's `lead_hours` feature will now carry meaningful information.

### 2. Live Observation Ingestion (MINOR CHANGE)

**Current**: `ingest_observations.py` already fetches from Open-Meteo Archive + ECCC.

**Change needed**: The Archive API has a ~5 day lag. For near-real-time observations, also query the **Open-Meteo Forecast API** with `past_hours=48` parameter, which returns the last 48h of ERA5T (preliminary reanalysis) data. This fills the gap until archive data arrives.

ECCC already provides data through yesterday — no change needed there.

### 3. Prediction Generation (CHANGE)

**Current**: Predictions are computed on-the-fly from historical data when the API is called.

**Change**: Add a **pre-computation step** that runs after each forecast ingestion:
1. Load the latest forecast run
2. Build features using latest observations + new forecast
3. Run all 5 models
4. Store predictions in a new `model_predictions` table (already in roadmap schema)
5. API endpoints read from this table instead of computing live

**Why pre-compute**: Feature building + model inference takes ~5-10 seconds. Pre-computing avoids this latency on every dashboard load.

### 4. Model Predictions Table (NEW MIGRATION)

```sql
CREATE TABLE model_predictions (
    id SERIAL PRIMARY KEY,
    model_version VARCHAR(50) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    target_time TIMESTAMPTZ NOT NULL,
    target_name VARCHAR(50) NOT NULL,
    predicted_value FLOAT,
    predicted_class VARCHAR(20),
    confidence FLOAT,
    forecast_run_id INTEGER REFERENCES forecast_runs(id)
);
CREATE INDEX ix_model_predictions_lookup
    ON model_predictions (target_name, location_id, target_time);
```

### 5. Evaluation Tracking (NEW MIGRATION)

Once observations arrive for a previously-predicted time, compute the actual error:

```sql
CREATE TABLE evaluation_metrics (
    id SERIAL PRIMARY KEY,
    model_version VARCHAR(50) NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    target_name VARCHAR(50) NOT NULL,
    horizon_hours INTEGER,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    mae FLOAT,
    rmse FLOAT,
    accuracy FLOAT,
    n_samples INTEGER
);
```

A daily job compares predictions from 24-48h ago against now-available observations.

---

## Updated Daily Pipeline

```
Schedule: Every 6 hours (aligned with GFS runs at 00, 06, 12, 18 UTC)

Step 1: Ingest latest observations (ECCC + Open-Meteo)
Step 2: Ingest latest GFS forecast run (Open-Meteo Forecast API)
Step 3: Generate predictions for next 48h using latest forecast + obs
Step 4: Store predictions in model_predictions table
Step 5: Evaluate predictions from 24-48h ago against new observations
Step 6: Log metrics to evaluation_metrics table
```

### Weekly: Retrain models
- Include all data up to yesterday in the training set
- Validate on rolling 30-day window
- Auto-deploy if new model beats current on validation set

---

## Frontend Changes

### Dashboard updates:
- Default view shows **today + next 48h** (not the Nov 2025 demo period)
- "Last updated" timestamp from the latest `model_predictions.generated_at`
- Stat cards show the **latest prediction**, not a historical snapshot

### New "Performance" tab:
- Rolling 7-day and 30-day MAE for each target
- Chart: prediction vs actual over the last 30 days
- Alert if model degradation detected (MAE exceeds 2x baseline)

---

## Implementation Order

### Phase 1: Live Forecast Ingestion (1-2 days)
- [ ] Create `scripts/ingest_live_forecast.py`
- [ ] Test with one API call, verify ForecastRun + ForecastValues stored
- [ ] Add to daily_pipeline.py

### Phase 2: Pre-computed Predictions (1-2 days)
- [ ] Create `model_predictions` model + migration
- [ ] Create `scripts/generate_predictions.py`
- [ ] Update API endpoints to read from model_predictions table
- [ ] Fall back to on-the-fly computation if no pre-computed data

### Phase 3: Live Evaluation (1 day)
- [ ] Create `evaluation_metrics` model + migration
- [ ] Create `scripts/evaluate_live.py` — compares predictions vs observations
- [ ] Add to daily_pipeline.py

### Phase 4: Frontend Updates (1-2 days)
- [ ] Dashboard defaults to today's predictions
- [ ] "Last updated" indicator
- [ ] Performance tracking page

### Phase 5: Automated Retraining (1 day)
- [ ] Update `retrain_models.py` to use expanding training window
- [ ] Version models (include date in filename)
- [ ] Keep previous model as fallback

---

## API Changes Summary

| Endpoint | Current | After |
|----------|---------|-------|
| `GET /api/predictions` | On-the-fly from historical data | Pre-computed from model_predictions table |
| `GET /api/predictions/latest` | N/A | Latest 48h predictions for all targets |
| `GET /api/performance` | N/A | Rolling MAE/accuracy from evaluation_metrics |
| `GET /health/detailed` | Shows data ages | Also shows prediction freshness |

---

## Key Risk: Model Drift

The models were trained on 2022-2024 data. As time passes:
- Weather patterns may shift (climate change, seasonal anomalies)
- API data format could change
- Model performance will degrade

**Mitigation**: The evaluation pipeline detects drift. If 30-day rolling MAE exceeds 1.5x the test-period MAE, trigger an alert and automatic retrain.
