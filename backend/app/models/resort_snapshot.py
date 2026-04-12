from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResortForecastSnapshot(Base):
    __tablename__ = "resort_forecast_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_day: Mapped[date] = mapped_column(Date, nullable=False)
    alpine_temp_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wind_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    freezing_level_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snow_accumulation_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synopsis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
