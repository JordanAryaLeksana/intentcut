"""Real PostgreSQL fixtures: isolated schemas inside an explicitly named test DB."""

import os
import subprocess
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from intentcut.backend.app import create_app
from intentcut.backend.backend_settings import BackendSettings
from intentcut.backend.database import Database
from intentcut.backend.local_media_storage import LocalMediaStorage


@pytest.fixture(scope="session")
def postgres_url():
    value = os.environ.get("TEST_DATABASE_URL") or dotenv_values(".env").get(
        "TEST_DATABASE_URL"
    )
    if not value:
        pytest.skip(
            "PostgreSQL pending: set TEST_DATABASE_URL to run real database tests"
        )
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith(
        "_test"
    ):
        pytest.fail("TEST_DATABASE_URL must use psycopg and a database ending in _test")
    # No skip on missing drivers, unreachable servers, 
    # or schema failures once configured.
    return value


@pytest.fixture
def database(postgres_url):
    schema = f"test_{uuid4().hex}"
    admin = create_engine(postgres_url, connect_args={"connect_timeout": 5})
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(
        postgres_url,
        connect_args={"connect_timeout": 5, "options": f"-csearch_path={schema}"},
    )
    database = Database(engine)
    try:
        database.initialize_schema()
        yield database
    finally:
        database.close()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def settings(tmp_path, postgres_url):
    return BackendSettings(
        _env_file=None,
        database_url=postgres_url,
        media_root=tmp_path / "media",
        max_file_bytes=1024 * 1024,
        max_request_bytes=3 * 1024 * 1024,
        max_upload_files=3,
    )


@pytest.fixture
def storage(settings):
    storage = LocalMediaStorage(
        settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
    )
    storage.initialize()
    return storage


@pytest.fixture
def client(settings, database, storage):
    # No fake probe or filesystem: FFprobe reads real staged media.
    app = create_app(settings, database=database, storage=storage)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def project(client):
    response = client.post("/projects", json={"name": "Integration project"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="session")
def clip_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("ingestion-media") / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:r=24:d=0.25",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path.read_bytes()
