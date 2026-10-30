"""Muse Image single-shot JSON API; fixed host, one output, no implicit retry."""

import base64
import binascii
import http.client
import json
from contextlib import closing
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from intentcut.backend.artifacts.derived import IMAGE_LIMIT
from intentcut.backend.contracts import AIProcessingError

MODEL = "muse-image-1.0"
MAX_RESPONSE = 24 * 1024 * 1024
SIZES = {"thumbnail": "1792x1024", "cover": "1536x1024", "poster": "1024x1536"}


def parse_image_response(data: bytes) -> bytes:
    try:
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("output_format") != "png":
            raise ValueError("Unexpected image encoding")
        items = value.get("data")
        if (
            not isinstance(items, list)
            or len(items) != 1
            or not isinstance(items[0], dict)
        ):
            raise ValueError("Expected exactly one image")
        encoded = items[0].get("b64_json")
        if (
            not isinstance(encoded, str)
            or "url" in items[0]
            or len(encoded) > IMAGE_LIMIT * 4 // 3 + 4
        ):
            raise ValueError("Expected bounded embedded image")
        image = base64.b64decode(encoded, validate=True)
        if not 0 < len(image) <= IMAGE_LIMIT or not image.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise ValueError("Invalid PNG payload")
        return image
    except (ValueError, TypeError, binascii.Error, RecursionError) as exc:
        raise AIProcessingError("invalid_image_output") from exc


class MuseImageClient:
    def __init__(
        self, api_key: SecretStr, *, timeout: float = 240, connection_factory=None
    ):
        self._key, self._timeout = api_key, timeout
        self._connection = connection_factory or http.client.HTTPSConnection

    def generate(
        self,
        prompt: str,
        preset: str,
        request_id: UUID,
        source: Path | None = None,
        content_type: str | None = None,
    ) -> bytes:
        body = {
            "model": MODEL,
            "prompt": prompt,
            "n": 1,
            "size": SIZES[preset],
            "response_format": "b64_json",
            "output_format": "png",
            "reasoning_strength": "low",
            "tool_enablement": {
                "enable_image_search": False,
                "enable_web_search": False,
                "enable_shell": False,
            },
        }
        endpoint = "/v1/images/generations"
        if source is not None:
            data = source.read_bytes()
            if not 0 < len(data) <= IMAGE_LIMIT or content_type not in {
                "image/png",
                "image/jpeg",
            }:
                raise AIProcessingError("source_unavailable")
            body["images"] = [
                {
                    "image_url": f"data:{content_type};base64,"
                    + base64.b64encode(data).decode("ascii")
                }
            ]
            endpoint = "/v1/images/edits"
        try:
            with closing(
                self._connection("api.meta.ai", timeout=self._timeout)
            ) as connection:
                connection.request(
                    "POST",
                    endpoint,
                    body=json.dumps(body).encode(),
                    headers={
                        "Authorization": f"Bearer {self._key.get_secret_value()}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                with closing(connection.getresponse()) as response:
                    if response.status != 200:
                        raise AIProcessingError(
                            "image_rate_limited"
                            if response.status == 429
                            else "provider_unavailable"
                        )
                    if (
                        response.getheader("Content-Type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                        != "application/json"
                    ):
                        raise AIProcessingError("invalid_image_output")
                    data = response.read(MAX_RESPONSE + 1)
                    if len(data) > MAX_RESPONSE:
                        raise AIProcessingError("invalid_image_output")
        except (OSError, http.client.HTTPException) as exc:
            raise AIProcessingError("image_outcome_unknown") from exc
        return parse_image_response(data)
