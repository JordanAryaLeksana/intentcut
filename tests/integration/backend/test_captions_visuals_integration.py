"""Combined migration and captions-to-visuals workflow; no live provider calls."""

from pathlib import Path
from uuid import UUID

import pytest
import test_caption_editing as captions
import test_visual_assets as visuals
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.app import create_app

source = captions.source
audio_videos = captions.audio_videos
transcript = captions.transcript
image_bytes = visuals.image_bytes
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_combined_migrations_from_pre004_preserve_legacy_results(
    database, storage, processing_result
):
    project = database.create_project("Legacy preservation").id
    job = database.create_ai_job(project, {"pipeline_version": "uploaded_v1"})
    claimed = database.claim_next_ai_job(job_id=job.id)
    assert AIArtifactPublisher(storage).publish_and_complete(
        database, project, job.id, claimed.lease_token, processing_result
    )
    original = [
        (a.id, a.sha256) for a in database.list_ai_job_artifacts(project, job.id)
    ]
    with database.engine.begin() as connection:
        # Only this fixture's disposable schema is altered, never public/dev tables.
        assert connection.execute(
            text("SELECT current_schema() LIKE 'test_%'")
        ).scalar_one()
        connection.execute(text("DROP TABLE caption_sets, project_covers"))
        connection.execute(text("DROP INDEX uq_caption_export_revision"))
        for column in ("content_type", "parent_artifact_id", "parent_sha256"):
            connection.execute(
                text(f"ALTER TABLE ai_job_artifacts DROP COLUMN {column} CASCADE")
            )
        connection.execute(
            text("ALTER TABLE ai_job_artifacts DROP CONSTRAINT artifact_kind")
        )
        connection.execute(
            text(
                "ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_kind "
                "CHECK (kind IN ('video','storyboard'))"
            )
        )
    for _ in range(2):
        for name in (
            "004_derived_artifacts.sql",
            "005_caption_sets.sql",
            "006_project_covers.sql",
        ):
            with database.engine.begin() as connection:
                connection.execute(
                    text((Path("scripts/migrations") / name).read_text())
                )
    assert [
        (a.id, a.sha256) for a in database.list_ai_job_artifacts(project, job.id)
    ] == original
    assert database.get_ai_job(project, job.id).status == "succeeded"
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM caption_sets")).scalar_one()
            == 0
        )
        assert (
            connection.execute(text("SELECT count(*) FROM project_covers")).scalar_one()
            == 0
        )


def test_captioned_rendition_frame_edit_cover_and_download(
    database, storage, settings, transcript, image_bytes
):
    settings = settings.model_copy(
        update={
            "ai_jobs_local_enabled": True,
            "image_generation_enabled": True,
            "voice_transcription_enabled": True,
            "model_api_key": SecretStr("fixture-only"),
        }
    )
    with TestClient(
        create_app(settings, database=database, storage=storage),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 12345),
    ) as api:
        saved = captions.edit(
            api, captions.create(api, transcript), "VISIBLE CAPTION"
        ).json()
        burn = captions.export(api, saved)
        caption_worker = captions.executor(database, storage, settings)
        assert caption_worker.process_one(job_id=burn)
        rendition = database.list_ai_job_artifacts(transcript[0], burn)[0]
        rendered = storage.root / rendition.storage_key
        assert captions.whites(rendered, 0.8) > 0
        accepted = visuals.submit(
            api,
            transcript[0],
            operation="edit",
            source_artifact_id=str(rendition.id),
            frame_seconds=0.8,
        )
        assert accepted.status_code == 202, accepted.text
        image_job = UUID(accepted.json()["id"])
        assert not caption_worker.process_one(job_id=image_job)
        provider = visuals.Provider(image_bytes)
        image_worker = visuals.worker(database, storage, settings, provider)
        assert image_worker.process_one(job_id=image_job)
        image = database.list_ai_job_artifacts(transcript[0], image_job)[0]
        assert image.parent_artifact_id == rendition.id
        assert image.parent_sha256 == rendition.sha256
        assert len(provider.calls) == 1 and provider.calls[0][3].startswith(b"\x89PNG")
        cover = api.put(
            visuals.path(transcript[0]) + "/cover",
            json={"artifact_id": str(image.id), "expected_revision": 0},
        )
        assert cover.status_code == 200, cover.text
        assert api.get(visuals.path(transcript[0])).json()["cover"] == cover.json()
        for job_id, artifact, content in [
            (burn, rendition, "video/mp4"),
            (image_job, image, "image/png"),
        ]:
            download = api.get(
                f"/projects/{transcript[0]}/ai-jobs/{job_id}/artifacts/{artifact.id}"
            )
            assert (
                download.status_code == 200
                and download.headers["content-type"] == content
            )
            assert (
                download.content == (storage.root / artifact.storage_key).read_bytes()
            )
        assert (
            api.get(captions.endpoint(transcript[0], f"/{saved['id']}")).json() == saved
        )
