from pydantic_settings import BaseSettings


def _normalize_db_url(url: str) -> str:
    # Railway/Heroku-style DATABASE_URL uses postgres:// or postgresql://,
    # but we need the psycopg3 driver scheme.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/whistler_forecast"
    env: str = "development"
    openmeteo_base_url: str = "https://api.open-meteo.com/v1"
    openmeteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    openmeteo_historical_forecast_url: str = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    geomet_base_url: str = "https://api.weather.gc.ca"
    whistler_forecast_url: str = "https://www.whistlerblackcomb.com/the-mountain/mountain-conditions/snow-and-weather-report"

    # CORS: comma-separated origins, e.g. "http://localhost:3000,https://whistler.example.com"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # DB connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True

    # Twilio SMS alerts
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    alert_enabled: bool = False

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()
settings.database_url = _normalize_db_url(settings.database_url)
