"""PostgreSQL records. No filesystem I/O, HTTP types, or lazy relationships."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from intentcut.backend.ai_jobs import AIJobStatus


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for the two M1B tables."""


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="project_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="asset_size"),
        CheckConstraint(
            "duration_seconds > 0 AND duration_seconds < 'Infinity'::float8",
            name="asset_duration",
        ),
        CheckConstraint("width > 0 AND height > 0", name="asset_dimensions"),
        CheckConstraint(
            "frame_rate_numerator >= 0 AND frame_rate_denominator > 0",
            name="asset_frame_rate",
        ),
        CheckConstraint(
            "(audio_stream_index IS NULL AND audio_codec IS NULL "
            "AND audio_sample_rate IS NULL AND audio_channels IS NULL) OR "
            "(audio_stream_index IS NOT NULL AND audio_codec IS NOT NULL "
            "AND audio_sample_rate IS NOT NULL AND audio_channels IS NOT NULL)",
            name="asset_audio_fields",
        ),
        Index("ix_media_project_created_id", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float] = mapped_column(Double)
    video_stream_index: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    pixel_format: Mapped[str] = mapped_column(Text)
    frame_rate_numerator: Mapped[int] = mapped_column(BigInteger)
    frame_rate_denominator: Mapped[int] = mapped_column(BigInteger)
    audio_stream_index: Mapped[int | None] = mapped_column(Integer)
    audio_codec: Mapped[str | None] = mapped_column(Text)
    audio_sample_rate: Mapped[int | None] = mapped_column(Integer)
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIJob(Base):
    __tablename__ = "ai_jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ai_job_valid_status",
        ),
        CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'",
            name="ai_job_payload_object",
        ),
        Index(
            "ix_ai_jobs_status_created",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_ai_jobs_project_created",
            "project_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AIJobStatus.QUEUED.value,
        server_default=AIJobStatus.QUEUED.value,
    )

    request_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    lease_token: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    lease_expires_at : Mapped[DateTime | None]= mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
