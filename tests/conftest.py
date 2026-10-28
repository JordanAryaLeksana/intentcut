"""Local synthetic outputs shared by artifact unit and PostgreSQL tests."""

import subprocess

import pytest

from intentcut.backend.ai_processing_adapter import ProcessingResult


@pytest.fixture(scope="session")
def artifact_video_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("ai-artifact-video") / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=24:d=0.25",
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


@pytest.fixture
def processing_result(tmp_path, artifact_video_bytes):
    storyboard = tmp_path / "storyboard.json"
    storyboard.write_text('{"title": "Test", "selections": []}', encoding="utf-8")
    video = tmp_path / "result.mp4"
    video.write_bytes(artifact_video_bytes)
    return ProcessingResult(storyboard, video)


@pytest.fixture
def fake_muse():
    """Only provider calls are faked; extraction, render, DB and HTTP remain real."""
    from intentcut.ai.schemas import VideoUnderstandingResult
    from intentcut.ai.story_director import StorySelection

    class FakeMuse:
        def __init__(self):
            self.analyzed = []
            self.selections = []
            self.selection_indices = None
            self.on_select = None

        def analyze(self, clip):
            assert clip.is_file()
            self.analyzed.append(clip)
            return VideoUnderstandingResult.model_validate(
                {
                    "summary": "A colored establishing shot",
                    "scene_candidates": [
                        {
                            "description": "A visible colored frame",
                            "editorial_reason": "Establish the scene",
                            "start_seconds": None,
                            "end_seconds": None,
                        }
                    ],
                }
            )

        def select(self, evidence, intent, target_seconds):
            self.selections.append(evidence)
            if self.on_select is not None:
                self.on_select()
            indices = self.selection_indices
            if indices is None:
                indices = [item["window_index"] for item in reversed(evidence)]
            return StorySelection.model_validate(
                {
                    "title": "A color story",
                    "rationale": "Show contrasting scenes",
                    "selected_windows": [
                        {"window_index": index, "reason": "A contrast"}
                        for index in indices
                    ],
                }
            )

    return FakeMuse()
