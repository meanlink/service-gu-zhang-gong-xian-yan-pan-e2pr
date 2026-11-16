from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    calibration_scheme_id: Mapped[int | None] = mapped_column(ForeignKey('calibration_schemes.id'), nullable=True)
    calibration_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calibration_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    invalidation_reason: Mapped[str] = mapped_column(String(500), default='')
    invalidated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
