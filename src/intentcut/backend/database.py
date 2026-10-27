import re
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from intentcut.backend.ai_jobs import AIJobStatus
from intentcut.backend.database_models import AIJob, Base, MediaAsset, Project


class ProjectNotFound(Exception):
    """The requested parent project does not exist."""


class MediaNotFound(Exception):
    """The asset does not belong to the requested project, or does not exist."""


class CommitOutcomeUnknown(Exception):
    """COMMIT was attempted, but the client cannot confirm its result."""


class Database:
    """Own an engine and session factory, never a shared mutable Session."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def connect(cls, url: str) -> "Database":
        return cls(
            create_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=0,
                pool_timeout=5,
                connect_args={"connect_timeout": 5},
                hide_parameters=True,
            )
        )

    def initialize_schema(self) -> None:
        """Explicit setup only; create missing tables, never migrate existing ones."""
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def create_project(self, name: str) -> Project:
        with self._sessions.begin() as session:
            project = Project(name=name)
            session.add(project)
            session.flush()
        return project

    def require_project(self, project_id: UUID) -> None:
        with self._sessions() as session:
            if session.get(Project, project_id) is None:
                raise ProjectNotFound

    def save_media_assets(
        self, project_id: UUID, assets: Sequence[MediaAsset]
    ) -> list[MediaAsset]:
        """Flush the whole batch before COMMIT; distinguish uncertain commit errors."""
        with self._sessions() as session:
            if session.get(Project, project_id) is None:
                raise ProjectNotFound
            session.add_all(assets)
            # A failure here is a known rollback; Session.close discards the batch.
            session.flush()
            try:
                session.commit()
            except SQLAlchemyError as exc:
                # Do not tell the service to delete files after an uncertain COMMIT.
                raise CommitOutcomeUnknown from exc
        return list(assets)

    def find_media_assets(self, asset_ids: Sequence[UUID]) -> list[MediaAsset]:
        """Read the primary database on a new session to reconcile a lost ACK."""
        with self._sessions() as session:
            return list(
                session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
            )

    def list_media(self, project_id: UUID, limit: int, offset: int) -> list[MediaAsset]:
        with self._sessions() as session:
            if session.get(Project, project_id) is None:
                raise ProjectNotFound
            return list(
                session.scalars(
                    select(MediaAsset)
                    .where(MediaAsset.project_id == project_id)
                    .order_by(MediaAsset.created_at, MediaAsset.id)
                    .limit(limit)
                    .offset(offset)
                )
            )

    def get_media(self, project_id: UUID, media_id: UUID) -> MediaAsset:
        with self._sessions() as session:
            asset = session.scalar(
                select(MediaAsset).where(
                    MediaAsset.project_id == project_id, MediaAsset.id == media_id
                )
            )
            if asset is None:
                raise MediaNotFound
            return asset

    def create_ai_job(
        self,
        project_id: UUID,
        request_payload: dict[str, object],
    ) -> AIJob:
        """Create a queued AI job for an existing project."""

        with self._sessions.begin() as session:
            if session.get(Project, project_id) is None:
                raise ProjectNotFound

            job = AIJob(
                project_id=project_id,
                status=AIJobStatus.QUEUED.value,
                request_payload=request_payload,
            )

            session.add(job)
            session.flush()

        return job

    def get_ai_job(
        self,
        project_id: UUID,
        job_id: UUID,
    ) -> AIJob | None:
        """Read a job scoped to its project."""

        with self._sessions() as session:
            return session.scalar(
                select(AIJob).where(
                    AIJob.id == job_id,
                    AIJob.project_id == project_id,
                )
            )

    def claim_next_ai_job(self, *, lease_seconds:int = 120) -> AIJob | None:
        """Atomically claim the oldest available queued job."""
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        with self._sessions.begin() as session:
            job = session.scalar(
                select(AIJob)
                .where(AIJob.status == AIJobStatus.QUEUED.value)
                .order_by(AIJob.created_at, AIJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            if job is None:
                return None
            now = session.scalar(select(func.now()))
            job.status = AIJobStatus.RUNNING.value
            job.lease_token = uuid4()
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.attempt_count = (job.attempt_count or 0) + 1
            job.started_at = now
            job.updated_at = now

            session.flush()

        return job
    def complete_ai_job(
            self,
            project_id: UUID,
            job_id : UUID,
            lease_token: UUID,
    ) -> bool:

        if not isinstance(lease_token , UUID):
            raise ValueError("Invalid lease token")
        with self._sessions.begin() as session:
            updated_id = session.scalar(
                update(AIJob)
                .where(
                    AIJob.id == job_id,
                    AIJob.project_id == project_id,
                    AIJob.status == AIJobStatus.RUNNING.value,
                    AIJob.lease_token == lease_token,
                    AIJob.lease_expires_at > func.clock_timestamp()
                )
                .values(
                    status=AIJobStatus.SUCCEEDED.value,
                    error_code=None,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                )
                .returning(AIJob.id)
            )
            return updated_id is not None
    def fail_ai_job(
            self,
            project_id: UUID,
            job_id: UUID,
            lease_token: UUID,
            error_code: str,
    )-> bool:
        if not isinstance(lease_token, UUID):
            raise ValueError("Invalid lease token")

        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code):
            raise ValueError("Invalid AI job error code")

        with self._sessions.begin() as session:
            updated_id = session.scalar(
                update(AIJob)
                .where(
                    AIJob.id == job_id,
                    AIJob.project_id == project_id,
                    AIJob.status == AIJobStatus.RUNNING.value,
                      AIJob.lease_token == lease_token,
                    AIJob.lease_expires_at > func.clock_timestamp(),
                )
                .values(
                      status=AIJobStatus.FAILED.value,
                    error_code=error_code,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                )
                .returning(AIJob.id)
            )

        return updated_id is not None

    def heartbeat_ai_job(
        self,
        project_id: UUID,
        job_id: UUID,
        lease_token: UUID,
        *,
        lease_seconds: int = 120,
    ) -> bool:
        """Renew an active lease owned by the supplied token."""

        if not isinstance(lease_token, UUID):
            raise ValueError("Invalid lease token")

        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")

        with self._sessions.begin() as session:
            now = session.scalar(select(func.now()))

            updated_id = session.scalar(
                update(AIJob)
                .where(
                    AIJob.id == job_id,
                    AIJob.project_id == project_id,
                    AIJob.status == AIJobStatus.RUNNING.value,
                    AIJob.lease_token == lease_token,
                    AIJob.lease_expires_at > now,
                )
                .values(
                    lease_expires_at=func.greatest(
                        AIJob.lease_expires_at,
                        now + timedelta(seconds=lease_seconds),
                    ),
                    updated_at=now,
                )
                .returning(AIJob.id)
            )

        return updated_id is not None

    def recover_expired_ai_job(
        self,
        *,
        max_attempts: int = 1,
    ) -> AIJob | None:
        """Recover one expired job using a bounded retry policy."""

        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= 3
        ):
            raise ValueError("Invalid maximum attempts")

        with self._sessions.begin() as session:
            job = session.scalar(
                select(AIJob)
                .where(
                    AIJob.status == AIJobStatus.RUNNING.value,
                    AIJob.lease_expires_at.is_not(None),
                    AIJob.lease_expires_at
                    <= func.clock_timestamp(),
                )
                .order_by(
                    AIJob.lease_expires_at,
                    AIJob.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            if job is None:
                return None

            now = session.scalar(
                select(func.clock_timestamp())
            )

            # Revoke previous worker ownership.
            job.lease_token = None
            job.lease_expires_at = None
            job.updated_at = now

            if job.attempt_count >= max_attempts:
                # No additional attempts are permitted.
                job.status = AIJobStatus.FAILED.value
                job.error_code = "worker_lease_expired"
                job.finished_at = now
            else:
                # Another worker may claim the job later.
                job.status = AIJobStatus.QUEUED.value
                job.started_at = None
                job.finished_at = None
                job.error_code = None

            session.flush()

        return job



def main() -> int:
    """Initialize the local schema deliberately, outside application startup."""
    from intentcut.backend.backend_settings import BackendSettings

    settings = BackendSettings()
    database = Database.connect(settings.database_url.get_secret_value())
    try:
        database.initialize_schema()
    finally:
        database.close()
    print("IntentCut database schema initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
