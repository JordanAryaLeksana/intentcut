import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intentcut.backend.database_models import AIJob


class CachedFirstCutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["first_cut"]
    intent: str = Field(min_length=1, max_length=1000)
    target_seconds: float = Field(
        gt=0,
        le=120,
        allow_inf_nan=False,
    )

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Intent cannot be blank")
        return value


@dataclass(frozen=True)
class ProcessingResult:
    storyboard_path: Path
    staged_video_path: Path


class RealAIProcessingAdapter:
    def __init__(
        self,
        *,
        repository_root: Path,
        evidence_directory: Path,
    ) -> None:
        self._root = repository_root.resolve()
        self._evidence = evidence_directory.resolve()

    def __call__(self, job: AIJob) -> ProcessingResult:
        request = CachedFirstCutRequest.model_validate(
            job.request_payload
        )

        if not os.getenv("MODEL_API_KEY"):
            raise RuntimeError("MODEL_API_KEY is not configured")

        evidence_files = sorted(
            self._evidence.glob("window_*.json")
        )

        if not evidence_files or len(evidence_files) > 12:
            raise ValueError("Expected 1 to 12 cached evidence files")

        if job.attempt_count is None or job.attempt_count < 1:
            raise ValueError("Job must be claimed before processing")

        # Each processing attempt owns its private workspace.
        workspace = (
            self._root
            / ".local"
            / "job_workspaces"
            / str(job.id)
            / f"attempt_{job.attempt_count:02d}"
        )

        workspace.mkdir(
            parents=True,
            exist_ok=False,
        )

        evidence_workspace = workspace / "evidence"
        evidence_workspace.mkdir()

        # Snapshot the previously validated evidence.
        for evidence_file in evidence_files:
            if evidence_file.is_symlink():
                raise ValueError("Symlinked evidence is not supported")

            shutil.copyfile(
                evidence_file,
                evidence_workspace / evidence_file.name,
            )

        storyboard = evidence_workspace / "storyboard_draft.json"
        output = workspace / "first_cut.mp4"

        self._run(
            [
                sys.executable,
                str(self._root / "scripts" / "story_director.py"),
                "--evidence",
                str(evidence_workspace),
                "--intent",
                request.intent,
                "--target-seconds",
                str(request.target_seconds),
                "--live",
            ],
            timeout=180,
            log_path=workspace / "story_director.log",
        )

        if not storyboard.is_file():
            raise RuntimeError("Story Director produced no storyboard")

        self._run(
            [
                sys.executable,
                str(self._root / "scripts" / "render_storyboard.py"),
                "--storyboard",
                str(storyboard),
                "--output",
                str(output),
            ],
            timeout=600,
            log_path=workspace / "renderer.log",
        )

        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("Renderer produced no MP4")

        self._run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(output),
                "-f",
                "null",
                "-",
            ],
            timeout=180,
            log_path=workspace / "decode.log",
        )

        return ProcessingResult(
            storyboard_path=storyboard,
            staged_video_path=output,
        )

    def _run(
        self,
        command: list[str],
        *,
        timeout: int,
        log_path: Path,
    ) -> None:
        with log_path.open("w", encoding="utf-8") as log:
            try:
                subprocess.run(
                    command,
                    cwd=self._root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Processing step timed out: {log_path.name}"
                ) from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Processing step failed: {log_path.name}"
                ) from exc
