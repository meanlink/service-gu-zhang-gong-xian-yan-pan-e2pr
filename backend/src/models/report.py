from sqlalchemy import String, Double, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    basis_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    basis_revoked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    revocation_note: Mapped[str] = mapped_column(String(500), default='')


class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    calibration_scheme_id: Mapped[int | None] = mapped_column(ForeignKey('calibration_schemes.id'), nullable=True)
    calibration_revision: Mapped[int | None] = mapped_column(nullable=True)
    basis_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    basis_revoked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    revocation_note: Mapped[str] = mapped_column(String(500), default='')
