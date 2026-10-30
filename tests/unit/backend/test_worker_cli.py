from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from intentcut.backend import worker_cli
from intentcut.backend.first_cut.media_inputs import processing_available


@pytest.mark.parametrize(
    "change",
    [
        {"ai_processing_enabled": False},
        {"model_api_key": None},
        {"model_api_key": SecretStr(" ")},
    ],
)
def test_worker_refuses_unconfigured_provider(settings, monkeypatch, change):
    settings = settings.model_copy(
        update={
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("test-secret"),
            **change,
        }
    )
    connect = Mock()
    monkeypatch.setattr(worker_cli.Database, "connect", connect)
    with pytest.raises(ValueError, match="not configured"):
        worker_cli.run_worker(settings)
    connect.assert_not_called()


def test_missing_ffmpeg_fails_closed(settings, monkeypatch):
    settings = settings.model_copy(
        update={
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("test-secret"),
        }
    )
    monkeypatch.setattr(
        "intentcut.backend.first_cut.media_inputs.shutil.which", lambda _: None
    )
    assert not processing_available(settings)


def test_cli_does_not_print_provider_credentials(settings, monkeypatch, capsys):
    monkeypatch.setattr(worker_cli, "BackendSettings", lambda: settings)
    monkeypatch.setattr(
        worker_cli,
        "run_worker",
        Mock(side_effect=RuntimeError("private-provider-secret")),
    )
    assert worker_cli.main([]) == 1
    output = capsys.readouterr()
    assert "private-provider-secret" not in output.err
    assert "RuntimeError" in output.err


def test_cli_shutdown(settings, monkeypatch, capsys):
    monkeypatch.setattr(worker_cli, "BackendSettings", lambda: settings)
    monkeypatch.setattr(worker_cli, "run_worker", Mock(side_effect=KeyboardInterrupt))
    assert worker_cli.main([]) == 130
    assert "interrupted" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--max-jobs", "0"], ["--max-attempts", "4"]])
def test_cli_budgets(args):
    with pytest.raises(SystemExit) as exc:
        worker_cli.main(args)
    assert exc.value.code == 2


def test_smoke_script_without_live_is_inert():
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "smoke_uploaded_job.py"
    result = subprocess.run(
        [sys.executable, str(script), "/nonexistent/footage.mp4"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert "No requests made" in result.stdout
    assert result.stderr == ""


def test_worker_loop_stays_inside_openai_context(settings, monkeypatch):
    """Regression: constructing Muse inside the context is not sufficient."""
    from contextlib import contextmanager

    state = {"open": False}
    client = object()
    database = Mock()
    storage = Mock()
    outcomes = iter([True, False])

    @contextmanager
    def openai(**kwargs):
        state["open"] = True
        try:
            yield client
        finally:
            state["open"] = False

    def muse(received):
        assert received is client and state["open"]
        return object()

    def process_one(**kwargs):
        assert state["open"], "The OpenAI client was closed before processing"
        return next(outcomes)

    database.recover_expired_ai_job.side_effect = lambda **kw: (
        state["open"] or pytest.fail("Recovery loop ran after client shutdown")
    )
    worker = Mock()
    worker.process_one.side_effect = process_one
    monkeypatch.setattr(worker_cli, "processing_available", lambda _: True)
    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    monkeypatch.setattr(worker_cli, "LocalMediaStorage", lambda *args: storage)
    monkeypatch.setattr(worker_cli, "OpenAI", openai)
    monkeypatch.setattr(worker_cli, "MuseClient", muse)
    monkeypatch.setattr(worker_cli, "RealAIProcessingAdapter", lambda **kw: Mock())
    monkeypatch.setattr(worker_cli, "AIJobWorker", lambda *args, **kw: worker)
    configured = settings.model_copy(update={"model_api_key": SecretStr("test-only")})
    assert worker_cli.run_worker(configured, max_jobs=2) == 1
    assert worker.process_one.call_count == 2
    assert not state["open"]
    database.close.assert_called_once()


def test_manual_only_never_initializes_openai(settings, monkeypatch):
    database = Mock()
    storage = Mock()
    worker = Mock()
    worker.process_one.return_value = False
    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    monkeypatch.setattr(worker_cli, "LocalMediaStorage", lambda *args: storage)
    monkeypatch.setattr(worker_cli, "AIJobWorker", lambda *args, **kw: worker)
    provider = Mock(side_effect=AssertionError("Provider must not initialize"))
    monkeypatch.setattr(worker_cli, "OpenAI", provider)
    monkeypatch.setattr(worker_cli, "MuseClient", provider)
    monkeypatch.setattr(worker_cli, "RealAIProcessingAdapter", provider)
    assert worker_cli.run_worker(settings, manual_only=True) == 0
    worker.process_one.assert_called_once_with(job_id=None, manual_only=True)
    database.recover_expired_ai_job.assert_called_once_with(
        max_attempts=1,
        job_id=None,
        manual_only=True,
        supported_job_types=("manual_v1",),
    )
    provider.assert_not_called()


@pytest.mark.parametrize("manual_only", [False, True])
def test_cli_registry_matches_recovery_and_executes_correct_handlers(
    settings, monkeypatch, manual_only
):
    from contextlib import contextmanager
    from pathlib import Path
    from uuid import uuid4

    from intentcut.backend.contracts import ProcessingResult, ProposalResult
    from intentcut.backend.jobs.dispatch import JobDispatcher
    from intentcut.backend.storage.database_models import AIJob

    state = {"open": False}
    database, storage = Mock(), Mock()
    media = ProcessingResult(Path("storyboard.json"), Path("video.mp4"))
    proposal = ProposalResult({})
    from intentcut.backend.artifacts.derived import ArtifactParent, VideoRenditionResult

    rendition = VideoRenditionResult(
        Path("captioned.mp4"), ArtifactParent(uuid4(), "a" * 64)
    )

    def handler(name, result):
        def run(job):
            assert state["open"] is (not manual_only)
            executed.append((name, job.request_payload["pipeline_version"]))
            return result

        return run

    executed = []
    manual = handler("manual", media)
    first_cut = handler("first-cut", media)
    revision = handler("revision", proposal)
    captions = handler("captions", rendition)

    @contextmanager
    def client(**kwargs):
        assert not manual_only
        state["open"] = True
        try:
            yield object()
        finally:
            state["open"] = False

    def worker_factory(received, dispatcher, **kwargs):
        assert received is database and isinstance(dispatcher, JobDispatcher)
        expected = (
            ("manual_v1",)
            if manual_only
            else ("manual_v1", "caption_burn_v1", "uploaded_v1", "revision_v1")
        )
        assert dispatcher.supported_job_types == expected

        def process(**kwargs):
            database.recover_expired_ai_job.assert_called_once_with(
                max_attempts=1,
                job_id=None,
                supported_job_types=expected,
                **({"manual_only": True} if manual_only else {}),
            )
            for kind in expected:
                result = dispatcher(
                    AIJob(
                        id=uuid4(),
                        project_id=uuid4(),
                        request_payload={"pipeline_version": kind},
                    )
                )
                assert result is (
                    proposal
                    if kind == "revision_v1"
                    else rendition
                    if kind == "caption_burn_v1"
                    else media
                )
            return False

        return Mock(process_one=process)

    monkeypatch.setattr(worker_cli, "processing_available", lambda _: True)
    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    monkeypatch.setattr(worker_cli, "LocalMediaStorage", lambda *args: storage)
    monkeypatch.setattr(worker_cli, "OpenAI", client)
    monkeypatch.setattr(worker_cli, "MuseClient", lambda client: object())
    monkeypatch.setattr(worker_cli, "RealAIProcessingAdapter", lambda **kw: first_cut)
    monkeypatch.setattr(worker_cli, "ManualRenderProcessor", lambda *args: manual)
    monkeypatch.setattr(worker_cli, "RevisionProcessor", lambda *args: revision)
    monkeypatch.setattr(worker_cli, "CaptionBurnProcessor", lambda *args: captions)
    monkeypatch.setattr(worker_cli, "AIJobWorker", worker_factory)
    configured = settings.model_copy(update={"model_api_key": SecretStr("fake-only")})
    assert worker_cli.run_worker(configured, manual_only=manual_only) == 0
    assert executed == (
        [("manual", "manual_v1")]
        if manual_only
        else [
            ("manual", "manual_v1"),
            ("captions", "caption_burn_v1"),
            ("first-cut", "uploaded_v1"),
            ("revision", "revision_v1"),
        ]
    )
    assert state["open"] is False
    database.close.assert_called_once()


def test_voice_only_never_opens_spark_client(settings, monkeypatch):
    database, storage, executor = Mock(), Mock(), Mock()
    executor.process_one.return_value = False
    captured = []

    def construct(db, dispatcher, **kwargs):
        captured.append(dispatcher)
        return executor

    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    monkeypatch.setattr(worker_cli, "LocalMediaStorage", lambda *a: storage)
    monkeypatch.setattr(worker_cli, "AIJobWorker", construct)
    monkeypatch.setattr(
        worker_cli, "OpenAI", Mock(side_effect=AssertionError("Spark must stay closed"))
    )
    configured = settings.model_copy(
        update={
            "voice_transcription_enabled": True,
            "ai_processing_enabled": False,
            "model_api_key": SecretStr("fake-only"),
        }
    )
    assert worker_cli.run_worker(configured, voice_only=True) == 0
    assert captured[0].supported_job_types == ("caption_transcribe_v1",)
    database.recover_expired_ai_job.assert_called_once_with(
        max_attempts=1, job_id=None, supported_job_types=("caption_transcribe_v1",)
    )
    database.close.assert_called_once()


def test_voice_only_requires_explicit_enablement(settings, monkeypatch):
    connect = Mock()
    monkeypatch.setattr(worker_cli.Database, "connect", connect)
    with pytest.raises(ValueError, match="not configured"):
        worker_cli.run_worker(settings, voice_only=True)
    with pytest.raises(ValueError, match="mutually exclusive"):
        worker_cli.run_worker(settings, voice_only=True, manual_only=True)
    connect.assert_not_called()
    with pytest.raises(SystemExit):
        worker_cli.main(["--voice-only", "--manual-only"])


def test_captions_only_is_provider_free(settings, monkeypatch):
    database, storage, worker = Mock(), Mock(), Mock()
    worker.process_one.return_value = False
    registered = []

    def construct(db, dispatcher, **kwargs):
        registered.append(dispatcher.supported_job_types)
        return worker

    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    monkeypatch.setattr(worker_cli, "LocalMediaStorage", lambda *a: storage)
    monkeypatch.setattr(worker_cli, "AIJobWorker", construct)
    monkeypatch.setattr(
        worker_cli, "OpenAI", Mock(side_effect=AssertionError("No provider"))
    )
    monkeypatch.setattr(
        worker_cli, "MuseVoiceClient", Mock(side_effect=AssertionError("No Voice"))
    )
    assert worker_cli.run_worker(settings, captions_only=True) == 0
    assert registered == [("caption_burn_v1",)]
    database.close.assert_called_once()
