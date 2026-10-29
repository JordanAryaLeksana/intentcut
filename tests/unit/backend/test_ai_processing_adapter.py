from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.first_cut.contracts import (
    FirstCutRequest,
    UploadedFirstCutRequest,
)


def test_reject_blank_intent():
    with pytest.raises(ValidationError):
        FirstCutRequest.model_validate(
            {
                "kind": "first_cut",
                "intent": "   ",
                "target_seconds": 10,
                "media_ids": [str(uuid4())],
            }
        )


def test_reject_invalid_duration():
    for seconds in (0, -1, float("inf"), 121):
        with pytest.raises(ValidationError):
            FirstCutRequest.model_validate(
                {
                    "kind": "first_cut",
                    "intent": "Create a coding video",
                    "target_seconds": seconds,
                    "media_ids": [str(uuid4())],
                }
            )


def test_adapter_rejects_legacy_cached_request(database, storage, settings):
    muse = Mock()
    adapter = RealAIProcessingAdapter(
        database=database, storage=storage, settings=settings, muse=muse
    )
    with pytest.raises(ValidationError):
        adapter(
            AIJob(
                id=uuid4(),
                request_payload={
                    "kind": "first_cut",
                    "intent": "old clip_b request",
                    "target_seconds": 10,
                },
            )
        )
    muse.analyze.assert_not_called()
    database.get_media.assert_not_called()
    assert not (storage.root / ".jobs").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": {}},
        {"pipeline_version": "cached"},
        {"source_sha256": {str(uuid4()): "a" * 64}},
    ],
)
def test_persisted_fingerprint_contract(change):
    media_id = str(uuid4())
    payload = {
        "kind": "first_cut",
        "intent": "story",
        "target_seconds": 10,
        "media_ids": [media_id],
        "pipeline_version": "uploaded_v1",
        "source_sha256": {media_id: "a" * 64},
        **change,
    }
    with pytest.raises(ValidationError):
        UploadedFirstCutRequest.model_validate(payload)
