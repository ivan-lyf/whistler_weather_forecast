from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelPrediction(Base):
    __tablename__ = "model_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("locations.id"), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_name: Mapped[str] = mapped_column(String(50), nullable=False)
    predicted_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("forecast_runs.id"), nullable=True)

    __table_args__ = (
        Index("ix_model_predictions_lookup", "target_name", "location_id", "target_time"),
    )
