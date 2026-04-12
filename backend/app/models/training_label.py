from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrainingLabel(Base):
    __tablename__ = "training_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("locations.id"), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label_24h_snowfall_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    label_6h_wind_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    label_12h_wind_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    label_freezing_level_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    label_precip_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        Index("ix_training_labels_location_time", "location_id", "target_time", unique=True),
    )
