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
    UniqueConstraint,
    Uuid,
    and_,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column

from intentcut.backend.jobs.domain import AIJobStatus


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata; initialized explicitly with create_all."""


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
        CheckConstraint(
            "progress IS NULL OR jsonb_typeof(progress) = 'object'",
            name="ai_job_progress_object",
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

    lease_expires_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    progress: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # Evaluated by PostgreSQL on each read, not persisted or exposed by the API.
    # An expired worker must not look active while waiting for recovery.
    has_active_lease: Mapped[bool] = column_property(
        and_(
            status == AIJobStatus.RUNNING.value,
            lease_token.is_not(None),
            lease_expires_at > func.clock_timestamp(),
        )
    )


class AIJobArtifact(Base):
    __tablename__ = "ai_job_artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", "kind", name="uq_ai_job_artifact_kind"),
        CheckConstraint(
            "kind IN ('video', 'storyboard', 'captions', 'image', 'rendition')",
            name="artifact_kind",
        ),
        CheckConstraint(
            "(parent_artifact_id IS NULL AND parent_sha256 IS NULL) OR "
            "(parent_artifact_id IS NOT NULL AND parent_sha256 IS NOT NULL "
            "AND parent_sha256 ~ '^[0-9a-f]{64}$')",
            name="artifact_parent_pair",
        ),
        CheckConstraint(
            "COALESCE((kind IN ('video','storyboard') AND content_type IS NULL "
            "AND parent_artifact_id IS NULL) OR "
            "(kind = 'captions' AND content_type = 'application/json' "
            "AND parent_artifact_id IS NOT NULL) OR "
            "(kind = 'image' AND content_type IN ('image/png','image/jpeg')) OR "
            "(kind = 'rendition' AND content_type = 'video/mp4' "
            "AND parent_artifact_id IS NOT NULL), false)",
            name="artifact_content_type",
        ),
        CheckConstraint("size_bytes > 0", name="artifact_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="artifact_sha256"),
        CheckConstraint(
            "storage_key ~ '^projects/[0-9a-f-]{36}/[0-9a-f-]{36}/original$'",
            name="artifact_storage_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("ai_jobs.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(32))
    parent_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "ai_job_artifacts.id", ondelete="RESTRICT", name="artifact_parent_fk"
        )
    )
    parent_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EditDraft(Base):
    """One mutable head; submitted job payloads retain immutable render revisions."""

    __tablename__ = "edit_drafts"
    __table_args__ = (
        CheckConstraint("revision > 0", name="edit_draft_revision"),
        CheckConstraint(
            "jsonb_typeof(window_indices) = 'array'", name="edit_draft_cuts"
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    base_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="RESTRICT")
    )
    base_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_job_artifacts.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    window_indices: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "uq_manual_render_revision",
    AIJob.project_id,
    AIJob.request_payload["draft_revision"].astext,
    unique=True,
    postgresql_where=AIJob.request_payload["pipeline_version"].astext == "manual_v1",
)


class RevisionProposal(Base):
    __tablename__ = "revision_proposals"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'accepted', 'rejected', 'stale')",
            name="revision_proposal_state",
        ),
        CheckConstraint(
            "result IS NULL OR jsonb_typeof(result) = 'object'",
            name="revision_proposal_result",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="RESTRICT"), primary_key=True
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProjectCover(Base):
    __tablename__ = "project_covers"
    __table_args__ = (
        CheckConstraint("revision > 0", name="project_cover_revision"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="project_cover_hash"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_job_artifacts.id", ondelete="RESTRICT")
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("ai_jobs.id", ondelete="RESTRICT"))
    sha256: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
