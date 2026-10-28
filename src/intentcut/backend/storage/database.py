import re
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from intentcut.backend.storage.database_models import (
    AIJob,
    AIJobArtifact,
    Base,
    MediaAsset,
    Project,
)
from intentcut.backend.jobs.domain import AIJobStatus
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown


class ProjectNotFound(Exception):
    """The requested parent project does not exist."""


class MediaNotFound(Exception):
    """The asset does not belong to the requested project, or does not exist."""


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
        """Retain published files after any failure once COMMIT is attempted."""
        commit_attempted = False
        try:
            with self._sessions() as session:
                if session.get(Project, project_id) is None:
                    raise ProjectNotFound
                session.add_all(assets)
                # A failure here is a known rollback; close discards the batch.
                session.flush()
                commit_attempted = True
                session.commit()
        except BaseException as exc:
            if commit_attempted:
                # Includes session cleanup after a successful COMMIT, as with
                # artifact completion. A lost acknowledgement cannot prove rollback.
                raise CommitOutcomeUnknown from exc
            raise
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

    def claim_next_ai_job(
        self, *, lease_seconds: int = 120, job_id: UUID | None = None
    ) -> AIJob | None:
        """Atomically claim the oldest available queued job."""
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        if job_id is not None and not isinstance(job_id, UUID):
            raise ValueError("Invalid job ID")
        with self._sessions.begin() as session:
            job = session.scalar(
                select(AIJob)
                .where(AIJob.status == AIJobStatus.QUEUED.value)
                .where(AIJob.id == job_id if job_id is not None else True)
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

    def complete_ai_job_with_artifacts(
        self,
        project_id: UUID,
        job_id: UUID,
        lease_token: UUID,
        artifacts: Sequence[AIJobArtifact],
    ) -> bool:
        """Register both final files and fence success in one short transaction.

        False and pre-COMMIT exceptions mean no changes committed. Once COMMIT
        is attempted, any exception is uncertain: callers must retain files.
        """
        if not isinstance(lease_token, UUID):
            raise ValueError("Invalid lease token")
        if len(artifacts) != 2 or {a.kind for a in artifacts} != {
            "video",
            "storyboard",
        }:
            raise ValueError("Both final artifact kinds are required")
        for artifact in artifacts:
            if (
                not isinstance(artifact.id, UUID)
                or artifact.job_id != job_id
                or artifact.storage_key
                != LocalMediaStorage.storage_key(project_id, artifact.id)
            ):
                raise ValueError("Invalid artifact ownership or storage key")

        commit_attempted = False
        try:
            with self._sessions() as session:
                # Serialize completion with heartbeat, recovery, and other workers.
                job = session.scalar(
                    select(AIJob)
                    .where(AIJob.id == job_id, AIJob.project_id == project_id)
                    .with_for_update()
                )
                now = session.scalar(select(func.clock_timestamp()))
                if (
                    job is None
                    or job.status != AIJobStatus.RUNNING.value
                    or job.lease_token != lease_token
                    or job.lease_expires_at is None
                    or job.lease_expires_at <= now
                ):
                    return False
                # Always INSERT. Never attach caller-owned ORM instances, which
                # could otherwise UPDATE an existing artifact after detachment.
                session.add_all(
                    [
                        AIJobArtifact(
                            id=a.id,
                            job_id=a.job_id,
                            kind=a.kind,
                            storage_key=a.storage_key,
                            size_bytes=a.size_bytes,
                            sha256=a.sha256,
                        )
                        for a in artifacts
                    ]
                )
                session.flush()
                # Recheck wall-clock expiry after inserts, while still holding the lock.
                updated_id = session.scalar(
                    update(AIJob)
                    .where(
                        AIJob.id == job_id,
                        AIJob.status == AIJobStatus.RUNNING.value,
                        AIJob.lease_token == lease_token,
                        AIJob.lease_expires_at > func.clock_timestamp(),
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
                if updated_id is None:
                    return False  # Session.close rolls back the inserted rows too.
                commit_attempted = True
                session.commit()
                return True
        except BaseException as exc:
            if commit_attempted:
                # Includes failures returning a connection after a successful COMMIT.
                raise CommitOutcomeUnknown from exc
            raise

    def list_ai_job_artifacts(
        self, project_id: UUID, job_id: UUID
    ) -> list[AIJobArtifact]:
        """Read final references scoped through the owning project."""
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(AIJobArtifact)
                    .join(AIJob)
                    .where(
                        AIJob.project_id == project_id, AIJobArtifact.job_id == job_id
                    )
                    .order_by(AIJobArtifact.kind)
                )
            )

    def fail_ai_job(
        self,
        project_id: UUID,
        job_id: UUID,
        lease_token: UUID,
        error_code: str,
    ) -> bool:
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
        job_id: UUID | None = None,
    ) -> AIJob | None:
        """Recover one expired job using a bounded retry policy."""

        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= 3
        ):
            raise ValueError("Invalid maximum attempts")
        if job_id is not None and not isinstance(job_id, UUID):
            raise ValueError("Invalid job ID")

        with self._sessions.begin() as session:
            job = session.scalar(
                select(AIJob)
                .where(AIJob.id == job_id if job_id is not None else True)
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
    from intentcut.backend.shared.settings import BackendSettings

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
