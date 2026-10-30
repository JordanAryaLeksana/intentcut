import json
from tempfile import SpooledTemporaryFile

import anyio
import pytest
from starlette.requests import ClientDisconnect

from intentcut.backend.app import create_app
from intentcut.backend.shared.upload_limits import UploadLimitsMiddleware


def test_declared_request_limit_is_checked_before_service(client, project, database):
    result = client.post(f"/projects/{project.id}/media", content=b"x" * 8193)
    assert result.status_code == 413
    assert result.json()["code"] == "upload_limit"
    database.require_project.assert_not_called()


def test_file_count_limit_during_parsing_closes_all_spools(
    client, project, monkeypatch
):
    spools = []

    def spool(*args, **kwargs):
        result = SpooledTemporaryFile(*args, **kwargs)  # noqa: SIM115 - parser owns it
        spools.append(result)
        return result

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", spool)
    result = client.post(
        f"/projects/{project.id}/media",
        files=[("files", (f"{i}.mp4", b"x")) for i in range(3)],
    )
    assert result.status_code == 413, result.text
    assert spools and all(item.closed for item in spools)


def test_success_closes_borrowed_upload_streams(client, project, monkeypatch):
    spools = []

    def spool(*args, **kwargs):
        result = SpooledTemporaryFile(*args, **kwargs)  # noqa: SIM115 - parser owns it
        spools.append(result)
        return result

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", spool)
    assert (
        client.post(
            f"/projects/{project.id}/media", files={"files": ("a.mp4", b"x")}
        ).status_code
        == 201
    )
    assert spools and all(item.closed for item in spools)


@pytest.mark.parametrize("disconnect", [False, True])
def test_stream_limit_or_disconnect_cleans_parser_spools(
    settings, database, storage, probe, project, monkeypatch, disconnect
):
    spools = []

    def spool(*args, **kwargs):
        result = SpooledTemporaryFile(*args, **kwargs)  # noqa: SIM115 - parser owns it
        spools.append(result)
        return result

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", spool)
    app = create_app(settings, database=database, storage=storage, probe=probe)
    prefix = (
        b'--boundary\r\nContent-Disposition: form-data; name="files"; '
        b'filename="a.mp4"\r\n\r\n'
    )
    incoming = [
        {"type": "http.request", "body": prefix + b"x" * 100, "more_body": True},
        {"type": "http.disconnect"}
        if disconnect
        else {"type": "http.request", "body": b"x" * 8192, "more_body": True},
    ]
    sent = []

    async def exercise():
        async def receive():
            return incoming.pop(0)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": f"/projects/{project.id}/media",
            "query_string": b"",
            "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
            "root_path": "",
        }
        if disconnect:
            with pytest.raises(ClientDisconnect):
                await app(scope, receive, send)
        else:
            await app(scope, receive, send)
            assert sent[0]["status"] == 413
            body = b"".join(message.get("body", b"") for message in sent)
            assert json.loads(body)["code"] == "upload_limit"

    anyio.run(exercise)
    assert spools and all(item.closed for item in spools)
    probe.probe.assert_not_called()
    assert not list(storage.root.rglob("original"))


def test_upload_admission_rejects_second_request_and_releases_slot():
    async def exercise():
        entered, release = anyio.Event(), anyio.Event()

        async def endpoint(scope, receive, send):
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = UploadLimitsMiddleware(endpoint, max_body_bytes=1024)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/projects/id/media",
            "headers": [],
        }
        first, second, third = [], [], []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def call(messages):
            async def send(message):
                messages.append(message)

            await middleware(dict(scope), receive, send)

        async with anyio.create_task_group() as group:
            group.start_soon(call, first)
            await entered.wait()
            await call(second)
            assert second[0]["status"] == 503
            release.set()
        await call(third)
        assert first[0]["status"] == third[0]["status"] == 204

    anyio.run(exercise)
