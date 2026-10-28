from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from intentcut.backend.app import create_app
from intentcut.backend.storage.database import Database, MediaNotFound, ProjectNotFound
from intentcut.backend.storage.database_models import Project
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.backend.media_ingestion.service import MediaIngestionService
from intentcut.backend.shared.settings import BackendSettings
from intentcut.media.models import AudioStream, MediaMetadata, VideoStream
from intentcut.media.probe_parser import MediaProbe


@pytest.fixture
def settings(tmp_path):
    return BackendSettings(
        _env_file=None,
        database_url="postgresql+psycopg://unused:unused@localhost/intentcut_test",
        media_root=tmp_path / "media",
        max_file_bytes=2048,
        max_request_bytes=8192,
        copy_chunk_bytes=64,
        max_upload_files=2,
    )


@pytest.fixture
def metadata():
    return MediaMetadata(
        Path("private/staged.part"),
        1.25,
        VideoStream(0, "h264", 320, 180, "yuv420p", Fraction(24), Fraction(24), 0),
        AudioStream(1, "aac", 44100, 1, 0),
    )


@pytest.fixture
def probe(metadata):
    probe = create_autospec(MediaProbe, instance=True)
    probe.probe.return_value = metadata
    return probe


@pytest.fixture
def database():
    """Behavioral double for unit tests only; integration tests use PostgreSQL."""
    database = create_autospec(Database, instance=True)
    projects = {}
    assets = {}

    def create(name):
        project = Project(id=uuid4(), name=name, created_at=datetime.now(UTC))
        projects[project.id] = project
        return project

    def require(project_id):
        if project_id not in projects:
            raise ProjectNotFound

    def save(project_id, batch):
        require(project_id)
        for asset in batch:
            asset.created_at = datetime.now(UTC)
            assets[asset.id] = asset
        return batch

    def listing(project_id, limit, offset):
        require(project_id)
        selected = sorted(
            (asset for asset in assets.values() if asset.project_id == project_id),
            key=lambda asset: (asset.created_at, asset.id),
        )
        return selected[offset : offset + limit]

    def get(project_id, media_id):
        asset = assets.get(media_id)
        if asset is None or asset.project_id != project_id:
            raise MediaNotFound
        return asset

    database.create_project.side_effect = create
    database.require_project.side_effect = require
    database.save_media_assets.side_effect = save
    database.list_media.side_effect = listing
    database.get_media.side_effect = get
    database.find_media_assets.side_effect = lambda ids: [
        assets[media_id] for media_id in ids if media_id in assets
    ]
    return database


@pytest.fixture
def project(database):
    return database.create_project("A local project")


@pytest.fixture
def storage(settings):
    storage = LocalMediaStorage(
        settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
    )
    storage.initialize()
    return storage


@pytest.fixture
def service(settings, database, storage, probe):
    return MediaIngestionService(database, storage, probe, settings.max_upload_files)


@pytest.fixture
def client(settings, database, storage, probe):
    app = create_app(settings, database=database, storage=storage, probe=probe)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
