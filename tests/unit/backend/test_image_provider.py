"""Official image endpoint JSON, bounded response and one-call HTTP lifecycle."""

import base64
import io
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr

from intentcut.ai.image import MuseImageClient, parse_image_response
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.visuals.contracts import VisualRequest

# Protocol-only bytes; actual decoding is covered by real PNG integration fixtures.
PNG = b"\x89PNG\r\n\x1a\nfixture"


def body(**changes):
    return json.dumps(
        {
            "data": [{"b64_json": base64.b64encode(PNG).decode()}],
            "output_format": "png",
            **changes,
        }
    ).encode()


class Response(io.BytesIO):
    status = 200

    def getheader(self, name, default=None):
        return "application/json" if name == "Content-Type" else default


class Connection:
    def __init__(self, response):
        self.response, self.calls, self.closed = response, [], False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@pytest.mark.parametrize("editing", [False, True])
def test_exact_json_request_no_urls_or_retry(tmp_path, editing):
    source = tmp_path / "reference.png"
    source.write_bytes(PNG)
    response = Response(body())
    connection = Connection(response)
    client = MuseImageClient(
        SecretStr("fake-key"), connection_factory=lambda *a, **kw: connection
    )
    assert (
        client.generate(
            "Make cover",
            "cover",
            uuid4(),
            source if editing else None,
            "image/png" if editing else None,
        )
        == PNG
    )
    args, kwargs = connection.calls[0]
    assert args == ("POST", "/v1/images/edits" if editing else "/v1/images/generations")
    request = json.loads(kwargs["body"])
    assert request["model"] == "muse-image-1.0" and request["n"] == 1
    assert (
        request["response_format"] == "b64_json" and request["output_format"] == "png"
    )
    assert all(v is False for v in request["tool_enablement"].values())
    if editing:
        assert request["images"] == [
            {"image_url": "data:image/png;base64," + base64.b64encode(PNG).decode()}
        ]
    else:
        assert "images" not in request
    assert kwargs["headers"]["Authorization"] == "Bearer fake-key"
    assert connection.closed and response.closed and len(connection.calls) == 1


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        b"[]",
        body(data=[]),
        body(data=[{}, {}]),
        body(output_format="webp"),
        body(data=[{"url": "https://example.com/private"}]),
        body(data=[{"b64_json": "!!!"}]),
        body(data=[{"b64_json": base64.b64encode(b"wrong").decode()}]),
    ],
)
def test_invalid_image_response(data):
    with pytest.raises(AIProcessingError, match="invalid_image_output"):
        parse_image_response(data)


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500])
def test_status_errors_are_safe_and_never_retry(status):
    response = Response(b"private provider details")
    response.status = status
    connection = Connection(response)
    client = MuseImageClient(
        SecretStr("fake-key"), connection_factory=lambda *a, **kw: connection
    )
    with pytest.raises(AIProcessingError) as error:
        client.generate("prompt", "thumbnail", uuid4())
    assert error.value.code == (
        "image_rate_limited" if status == 429 else "provider_unavailable"
    )
    assert len(connection.calls) == 1 and connection.closed and response.closed
    assert "private" not in str(error.value)


def test_timeout_is_uncertain_and_connection_closes():
    connection = Connection(None)

    def timeout():
        raise TimeoutError("private")

    connection.getresponse = timeout
    with pytest.raises(AIProcessingError, match="image_outcome_unknown"):
        MuseImageClient(
            SecretStr("fake"), connection_factory=lambda *a, **kw: connection
        ).generate("prompt", "cover", uuid4())
    assert connection.closed and len(connection.calls) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"operation": "edit"},
        {"source_artifact_id": str(uuid4())},
        {"frame_seconds": 1},
        {"frame_seconds": float("nan")},
        {"prompt": " "},
        {"prompt": "bad\x00"},
        {"prompt": "x" * 2001},
        {"url": "https://example.com"},
    ],
)
def test_admission_contract_rejects_invalid(patch):
    with pytest.raises(ValueError):
        VisualRequest(request_id=uuid4(), **{"prompt": "cover", **patch})


def test_missing_media_tools_prevents_provider_admission(monkeypatch, settings):
    from pydantic import SecretStr

    from intentcut.backend.visuals.service import image_available

    configured = settings.model_copy(
        update={
            "image_generation_enabled": True,
            "model_api_key": SecretStr("fake-key"),
        }
    )
    monkeypatch.setattr(
        "intentcut.backend.visuals.service.shutil.which", lambda _: None
    )
    assert not image_available(configured)
