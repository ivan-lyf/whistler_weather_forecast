# Whistler Blackcomb Forecast App Roadmap

## Goal

Build a mountain-specific forecast app for Whistler Blackcomb that improves on generic weather forecasts by learning local forecast errors using:

* archived forecast model outputs
* historical observations
* Whistler-specific forecast signals
* ML-based correction models

The first version should **not** try to build a weather simulator from scratch. It should build a **forecast correction system**.

---

## 1. Product Definition

### Core user questions

Your app should answer:

* How much snow will fall in the next 6h / 12h / 24h?
* Will it be rain, mixed, or snow at base / mid / alpine?
* How strong will alpine wind be?
* What is the freezing level?
* How confident is the forecast?

### MVP forecast targets

Start with only these 4:

1. 24h snowfall at alpine
2. 6h / 12h alpine wind risk
3. freezing level
4. precipitation type at base / mid / alpine

### Elevation bands

Use fixed target bands from day 1:

* Base: ~675 m
* Mid: ~1500 m
* Alpine: ~2000–2284 m

---

## 2. Recommended Tech Stack

### Backend

* Python
* FastAPI
* Pydantic
* SQLAlchemy or SQLModel
* Alembic migrations

### Data / ML

* pandas to start
* polars later if needed
* scikit-learn
* LightGBM
* optional: XGBoost
* Jupyter notebooks for experiments

### Database

* PostgreSQL
* TimescaleDB extension

### Frontend

* Next.js
* TypeScript
* Tailwind CSS
* Recharts or ECharts

### Infra

* Docker + Docker Compose
* GitHub Actions
* cron or scheduled jobs
* deploy later on Render / Railway / Fly.io / VPS

---

## 3. System Architecture

### Data collectors

* historical observation collector
* archived forecast collector
* resort forecast snapshotter
* feature builder

### Storage

Store:

* raw source payloads
* cleaned hourly observations
* archived forecast runs
* features for training
* model predictions
* evaluation metrics

### Services

* ingestion services
* training/backtest service
* prediction service
* API server
* frontend dashboard

---

## 4. Data You Need to Collect

## A. Historical observations

Purpose: create the ground-truth labels.

Collect hourly data such as:

* observation time
* station id
* temperature
* precipitation
* snowfall if available
* snow depth if available
* wind speed
* wind gust
* humidity
* pressure

### Suggested sources

Primary:

* ECCC / GeoMet

Optional fallback:

* Meteostat

### Notes

Use ECCC/GeoMet as your source of truth if possible. Meteostat is helpful for developer convenience, but treat it as a fallback or auxiliary source.

---

## B. Archived past forecasts

Purpose: train the correction model on what forecast systems predicted *before* the weather happened.

This is the most important ML input.

Collect:

* provider
* model name
* run time / issue time
* valid time
* temperature
* precipitation
* snowfall
* wind speed
* gusts
* humidity
* pressure
* freezing-level-related fields if available
* weather code

### Suggested source

* Open-Meteo archived / historical forecast data

### Important rule

Never replace old forecast runs with newer data. You need the original run so that your backtests are honest.

---

## C. Official Whistler Blackcomb forecast snapshots

Purpose:

* benchmark your model against the official resort forecast
* display a side-by-side comparison in the app

Collect every hour if possible:

* snapshot time
* alpine temperature
* wind field
* freezing level
* snow accumulation text
* text summary
* raw HTML snapshot

### Important note

This is not the main ML source. It is mainly for comparison and user-facing presentation.

---

## D. Derived labels

You need a clean label table for supervised learning.

Create labels for:

* 24h snowfall
* 6h / 12h alpine wind
* freezing level
* precip type at base / mid / alpine

---

## 5. Database Design

Use **PostgreSQL + TimescaleDB**.

### Why

* SQL is easier to reason about than a pure document store
* time-series data fits very naturally
* good support from Python
* good for metrics and analytics

## Suggested tables

### `locations`

Stores target forecast points.

Fields:

* id
* name (`base`, `mid`, `alpine`)
* latitude
* longitude
* elevation_m

### `stations`

Stores observation sources.

Fields:

* id
* source
* external_station_id
* name
* latitude
* longitude
* elevation_m
* is_active

### `obs_hourly`

Stores hourly observed weather.

Fields:

* station_id
* observed_at
* temperature_c
* precip_mm
* snowfall_cm
* snow_depth_cm
* wind_speed_kmh
* wind_gust_kmh
* humidity_pct
* pressure_hpa
* raw_payload

Indexes:

* `(station_id, observed_at)`

### `forecast_runs`

Stores metadata about every archived forecast run.

Fields:

* id
* provider
* model_name
* run_at
* fetched_at
* raw_payload

Indexes:

* `(provider, model_name, run_at)`

### `forecast_values`

Stores forecast values by run, target point, and valid time.

Fields:

* forecast_run_id
* location_id
* valid_at
* lead_hours
* temperature_c
* precip_mm
* snowfall_cm
* wind_speed_kmh
* wind_gust_kmh
* humidity_pct
* pressure_hpa
* freezing_level_m
* weather_code

Indexes:

* `(location_id, valid_at)`
* `(forecast_run_id, valid_at)`

### `resort_forecast_snapshots`

Stores parsed official resort forecast fields.

Fields:

* snapshot_at
* forecast_day
* alpine_temp_text
* wind_text
* freezing_level_text
* snow_accumulation_text
* synopsis_text
* raw_html

### `training_labels`

Stores clean target values for supervised learning.

Fields:

* location_id
* target_time
* label_24h_snowfall_cm
* label_6h_wind_kmh
* label_12h_wind_kmh
* label_freezing_level_m
* label_precip_type

### `model_predictions`

Stores model outputs.

Fields:

* model_version
* generated_at
* location_id
* target_time
* pred_24h_snowfall_cm
* pred_6h_wind_kmh
* pred_12h_wind_kmh
* pred_freezing_level_m
* pred_precip_type
* confidence_score

### `evaluation_metrics`

Stores offline and live evaluation.

Fields:

* model_version
* evaluated_at
* target_name
* horizon_hours
* location_id
* mae
* rmse
* accuracy
* precision
* recall

---

## 6. Data Collection Plan

## Collector 1: observation backfill

Purpose: create labels.

### Steps

1. identify nearby stations
2. pull historical hourly observation data
3. standardize units and timestamps
4. fill missing timestamps where needed
5. store raw + cleaned versions

### Output tables

* `stations`
* `obs_hourly`

---

## Collector 2: archived forecast backfill

Purpose: create the forecast-side inputs.

### Steps

1. define target forecast locations for base / mid / alpine
2. pull archived forecast runs for each location
3. store run metadata separately from forecast values
4. flatten hourly forecast arrays into rows
5. compute lead time as `valid_at - run_at`

### Output tables

* `forecast_runs`
* `forecast_values`

---

## Collector 3: resort snapshotter

Purpose: compare your product against the official mountain forecast.

### Steps

1. request the forecast page
2. save raw HTML
3. parse the visible values
4. store structured snapshot rows

### Output tables

* `resort_forecast_snapshots`

---

## Collector 4: feature builder

Purpose: create ML-ready training rows.

### Suggested features

* latest raw forecast values
* previous forecast run delta
* last 6h / 12h / 24h observed snowfall / precip
* last 6h / 12h wind stats
* pressure trend
* temperature trend
* month
* hour of day
* elevation band
* precipitation trend
* recent forecast volatility

### Output

For MVP, you can export to parquet files or generate a materialized table.

---

## 7. ML Plan

## Core idea

Do not generate weather from scratch.

Train a model that learns:

`corrected forecast = raw forecast + local correction`

## First models

Train separate models.

### Model A: snowfall regression

Target:

* 24h alpine snowfall

Recommended model:

* LightGBM regressor

### Model B: wind regression / risk classification

Targets:

* 6h alpine wind
* 12h alpine wind
* optional: high-wind risk class

### Model C: freezing level regression

Target:

* freezing_level_m

### Model D: precip-type classification

Target classes:

* rain
* mixed
* snow

## Why boosted trees first

This is structured tabular time-series data. Better features and honest backtests usually matter more than deep learning at the start.

## Split strategy

Use rolling time splits only.

Example:

* train: 2022–2024
* validate: early 2025
* test: late 2025

Do not use random train/test splitting.

## Metrics

Regression:

* MAE
* RMSE

Classification:

* accuracy
* precision
* recall
* confusion matrix

Mountain-useful event metrics:

* powder event detection
* rain-at-base detection
* alpine high-wind warning detection

---

## 8. MVP Scope

## MVP features

### Dashboard

* tabs for base / mid / alpine
* 48h hourly forecast chart
* 24h snowfall card
* freezing level chart
* wind warning card
* precipitation type timeline

### Comparison section

Show:

* official forecast
* raw model forecast
* your corrected forecast

### Metrics page

Show:

* rolling 30-day snowfall MAE
* rolling 30-day freezing-level MAE
* rolling 30-day wind MAE
* classification accuracy for precip type

## Not in MVP

Do not include yet:

* trail-level forecasts
* avalanche forecasting
* computer vision from webcams
* mobile app
* social feed
* custom deep neural nets

---

## 9. 8-Week Build Plan

## Week 1: project setup

Build:

* repo structure
* Docker Compose
* local Postgres + TimescaleDB
* backend skeleton
* frontend skeleton
* migrations
* env file structure

Deliverable:

* app runs locally
* backend connects to DB
* frontend shows dummy forecast cards

## Week 2: observation ingestion

Build:

* station lookup script
* historical observation collector
* cleaning pipeline
* charts for raw observation history

Deliverable:

* at least 1–2 years of hourly observations stored

## Week 3: archived forecast ingestion

Build:

* archived forecast collector
* run metadata storage
* hourly flattening
* lead-hour generation

Deliverable:

* archived forecast runs stored and queryable

## Week 4: labels + baselines

Build:

* label generation pipeline
* baseline evaluation scripts

Baselines:

* raw forecast
* persistence
* simple rules

Deliverable:

* first benchmark report

## Week 5: first ML model

Build:

* feature pipeline
* snowfall model
* rolling backtest

Deliverable:

* 24h alpine snowfall model

## Week 6: additional targets

Build:

* wind model
* freezing level model
* precip type classifier
* confidence scoring

Deliverable:

* full target set working offline

## Week 7: product MVP

Build:

* backend endpoints
* charts
* comparison UI
* metrics page

Deliverable:

* usable web dashboard

## Week 8: live pipeline + deployment

Build:

* scheduled ingestion
* scheduled predictions
* retraining job
* deployment
* basic monitoring

Deliverable:

* live app with automatic updates

---

## 10. What You Need To Do On Your End

This is the practical setup checklist.

## A. Install the core tools

You need:

* Git
* Docker Desktop
* Python 3.11+
* Node.js 20+
* a code editor like VS Code

Why:

* Docker runs your database and services locally
* Python handles ingestion and ML
* Node runs the frontend

---

## B. Decide your database setup

You have 2 good choices.

### Option 1: local database for development

Best for starting.

Use Docker Compose to run:

* PostgreSQL
* TimescaleDB

You should do this first.

### Option 2: managed database for deployment

Use later for production.

Possible options:

* Render Postgres
* Railway Postgres
* Neon Postgres
* Supabase Postgres

For this project, local Postgres first is easiest.

---

## C. Create a local Postgres + TimescaleDB instance

Use a `docker-compose.yml` with a TimescaleDB image.

Example:

```yaml
version: '3.9'
services:
  db:
    image: timescale/timescaledb:latest-pg16
    container_name: whistler_db
    environment:
      POSTGRES_DB: whistler_forecast
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - whistler_db_data:/var/lib/postgresql/data
volumes:
  whistler_db_data:
```

Then run:

```bash
docker compose up -d
```

---

## D. Create your database connection string

In your backend, you will need an environment variable like:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/whistler_forecast
```

If you use async SQLAlchemy later, the format may change slightly depending on your driver.

---

## E. Set up database migrations

Use Alembic.

You need to:

1. initialize Alembic
2. point it at `DATABASE_URL`
3. create migration files
4. run migrations

Typical commands:

```bash
alembic init migrations
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## F. Set up the forecast APIs / data sources

This project mostly uses public weather data, so the good news is that you may not need many API keys at the start.

### 1. Open-Meteo

Use for:

* archived forecast runs
* current forecast data

What you need to do:

* read their docs
* choose the variables you want
* write a collector script

API key needed:

* usually no key for basic public usage

### 2. ECCC / GeoMet

Use for:

* observation data
* Canadian weather/climate records

What you need to do:

* read their station / climate / observation docs
* find nearby stations
* write a collector script

API key needed:

* typically no key for public access

### 3. Meteostat (optional)

Use only if needed:

* easier developer workflow
* fallback data source

What you need to do:

* decide whether you need it at all
* use only for convenience, not your final truth source

### 4. Whistler Blackcomb official site

Use for:

* comparison snapshots only

What you need to do:

* check robots / terms before scraping
* store HTML snapshots carefully
* keep request rate low

There is likely no official public API for the resort forecast page, so this is a parser/scraper job, not a normal API integration.

---

## G. Create your `.env` file

You should create one `.env` file for local dev.

Example:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/whistler_forecast
ENV=development
OPENMETEO_BASE_URL=https://api.open-meteo.com/v1
GEOMET_BASE_URL=https://api.weather.gc.ca
WHISTLER_FORECAST_URL=https://www.whistlerblackcomb.com/the-mountain/mountain-conditions/snow-and-weather-report.aspx
```

You may add more later.

---

## H. Build the first backend endpoints

You do not need a huge API at first.

Start with:

* `GET /health`
* `GET /locations`
* `GET /forecast/hourly?location=alpine`
* `GET /forecast/current`
* `GET /metrics`

These are enough for MVP.

---

## I. Build the first ingestion scripts

You should make these as separate scripts or jobs:

* `ingest_observations.py`
* `ingest_archived_forecasts.py`
* `snapshot_resort_forecast.py`
* `build_features.py`
* `train_snowfall_model.py`
* `generate_predictions.py`

At the beginning, run them manually.
Later, schedule them.

---

## J. What accounts you likely need

For MVP, probably only:

* GitHub account
* hosting account later if deploying
* optional managed Postgres account later

You likely do **not** need paid API accounts for the first version if you use public sources.

---

## K. What you should do first this week

If you are starting from zero, do these in order:

1. install Docker, Python, Node, Git
2. create repo
3. create local Postgres + TimescaleDB with Docker Compose
4. set up FastAPI backend
5. set up Next.js frontend
6. create `.env`
7. create initial DB schema and migrations
8. write observation collector
9. write archived forecast collector
10. verify rows are entering the DB

That is the correct starting point.

---

## 11. Suggested Repo Structure

```text
whistler-forecast/
  apps/
    api/
    web/
  services/
    ingest-observations/
    ingest-forecasts/
    ingest-resort/
    train-models/
  packages/
    db/
    feature-engineering/
    shared-types/
  infra/
    docker/
    migrations/
  notebooks/
  data/
```

---

## 12. Best Order of Implementation

Build in this order:

1. database
2. observation ingestion
3. archived forecast ingestion
4. labels
5. baseline evaluation
6. first snowfall model
7. backend endpoints
8. frontend dashboard
9. live scheduled updates
10. retraining and monitoring

Do not start with the frontend alone. Get the data pipeline working first.

---

## 13. Biggest Risks

* trying to train on observations alone
* not storing past forecast runs correctly
* using random train/test split
* ignoring elevation bands
* scraping too aggressively
* building too many UI features before proving forecast value

---

## 14. Final MVP Definition

Your MVP is done when:

* observations are ingested and stored
* archived forecasts are ingested and stored
* one correction model works
* dashboard shows base / mid / alpine
* official vs raw vs corrected forecast comparison exists
* rolling metrics page exists
* live updates run on a schedule

That is already a strong project.

---

## 15. Best Practical Recommendation

Start with this exact stack and scope:

* PostgreSQL + TimescaleDB
* FastAPI backend
* Next.js frontend
* ECCC / GeoMet observations
* Open-Meteo archived forecasts
* official Whistler forecast snapshot comparison
* LightGBM models for:

  * 24h alpine snowfall
  * freezing level
  * precip type

This gives you the best balance of realism, usefulness, and finishability.
