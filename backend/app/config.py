from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/whistler_forecast"
    env: str = "development"
    openmeteo_base_url: str = "https://api.open-meteo.com/v1"
    geomet_base_url: str = "https://api.weather.gc.ca"
    whistler_forecast_url: str = "https://www.whistlerblackcomb.com/the-mountain/mountain-conditions/snow-and-weather-report"

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()
