import type { AIJobProgress, AIProgressStage } from "./contracts";
import { ApiError, isRecord } from "./transport";

export const PROGRESS_STAGES: readonly AIProgressStage[] = [
  "preparing_media", "extracting_audio", "transcribing_audio", "validating_transcript", "extracting_windows", "understanding_footage",
  "selecting_story", "revising_sequence", "rendering_video", "publishing_artifacts",
];

export function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

/** Pick public fields only. Never expose arbitrary provider metadata as UI copy. */
export function parseJobProgress(value: unknown): AIJobProgress | null {
  if (value == null) return null;
  if (!isRecord(value) || !PROGRESS_STAGES.includes(value.stage as AIProgressStage) ||
      !isTimestamp(value.stage_started_at) || !isTimestamp(value.updated_at) ||
      Date.parse(value.updated_at) < Date.parse(value.stage_started_at)) {
    throw new ApiError("Invalid AI progress response.", 0, "invalid_response");
  }
  const completed = value.completed_windows;
  const total = value.total_windows;
  const hasCounts = completed != null || total != null;
  if (hasCounts && (
    value.stage !== "understanding_footage" ||
    typeof completed !== "number" || !Number.isSafeInteger(completed) || completed < 0 ||
    typeof total !== "number" || !Number.isSafeInteger(total) || total < 1 || total > 12 ||
    completed > total
  )) {
    throw new ApiError("Invalid AI window counts.", 0, "invalid_response");
  }
  return {
    stage: value.stage as AIProgressStage,
    stage_started_at: value.stage_started_at,
    updated_at: value.updated_at,
    ...(hasCounts ? { completed_windows: completed as number, total_windows: total as number } : {}),
  };
}
