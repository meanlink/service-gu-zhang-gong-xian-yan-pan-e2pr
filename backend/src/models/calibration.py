from sqlalchemy import String, Double, ForeignKey, Integer, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class CalibrationScheme(Base):
    """一组服务间校时凭据；草稿发布后才能被分析试验选用。"""

    __tablename__ = 'calibration_schemes'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    reference_service: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft')
    revision: Mapped[int] = mapped_column(Integer, default=0)
    last_reconciled_revision: Mapped[int] = mapped_column(Integer, default=0)
    revocation_note: Mapped[str] = mapped_column(String(500), default='')
    created_by: Mapped[str] = mapped_column(String(150), default='')
    created_at: Mapped[float] = mapped_column(Double)
    published_by: Mapped[str] = mapped_column(String(150), default='')
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class CalibrationCredential(Base):
    """有向凭据 source→target：target 读数 - source 读数落在 [lower_min, upper_min]。"""

    __tablename__ = 'calibration_credentials'
    __table_args__ = (
        # 同一服务对同时只允许一条有效凭据；已撤销的凭据保留，允许重新登记。
        Index(
            'uq_calibration_active_pair',
            'scheme_id', 'source_service', 'target_service',
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey('calibration_schemes.id'))
    source_service: Mapped[str] = mapped_column(String(80))
    target_service: Mapped[str] = mapped_column(String(80))
    lower_min: Mapped[float] = mapped_column(Double)
    upper_min: Mapped[float] = mapped_column(Double)
    note: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(20), default='active')
    created_by: Mapped[str] = mapped_column(String(150), default='')
    created_at: Mapped[float] = mapped_column(Double)
    revoked_by: Mapped[str] = mapped_column(String(150), default='')
    revoked_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class CredentialRevocation(Base):
    """撤销登记，每个凭据至多一条；重试不会重复登记。"""

    __tablename__ = 'credential_revocations'
    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[int] = mapped_column(ForeignKey('calibration_credentials.id'), unique=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey('calibration_schemes.id'))
    reason: Mapped[str] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(150))
    at: Mapped[float] = mapped_column(Double)
    revision: Mapped[int] = mapped_column(Integer, default=0)
