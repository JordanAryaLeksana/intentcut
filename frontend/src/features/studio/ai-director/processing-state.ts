import type { AIJob, AIJobProgress, AIProgressStage } from "@/lib/api/contracts";

export interface ObservedJob extends AIJob {
  /** In-memory observation only; never represented as persisted stage history. */
  lastObservedProgress?: AIJobProgress;
}

export const STAGE_COPY: Record<AIProgressStage, { title: string; description: string }> = {
  preparing_media: { title: "Preparing media", description: "Checking the selected footage and verifying source files." },
  extracting_windows: { title: "Extracting windows", description: "Preparing video windows for analysis." },
  understanding_footage: { title: "Understanding footage", description: "Analyzing and validating evidence from your footage." },
  selecting_story: { title: "Selecting the story", description: "Choosing a sequence and validating the edit plan." },
  revising_sequence: { title: "Revising the sequence", description: "Preparing a supported cut-order proposal for your review." },
  rendering_video: { title: "Rendering video", description: "Rendering the selected sequence and validating the MP4." },
  publishing_artifacts: { title: "Publishing the first cut", description: "Verifying and saving the storyboard and rendered video." },
};

export function observeJob(previous: ObservedJob | undefined, next: AIJob): ObservedJob {
  const sameAttempt = previous?.id === next.id &&
    previous.attempt_count === next.attempt_count && previous.started_at === next.started_at;
  const observed = next.status === "running" && next.progress
    ? next.progress
    : sameAttempt ? previous.lastObservedProgress : undefined;
  return {
    ...next,
    lastObservedProgress: next.status === "queued" || next.status === "succeeded" ? undefined : observed,
  };
}

export function elapsedSeconds(job: AIJob, now: number | null): number | null {
  const start = Date.parse(job.created_at);
  const terminal = job.status === "succeeded" || job.status === "failed";
  const end = terminal ? (job.finished_at ? Date.parse(job.finished_at) : NaN) : now;
  if (!Number.isFinite(start) || end == null || !Number.isFinite(end)) return null;
  return Math.max(0, Math.floor((end - start) / 1000));
}

export function formatElapsed(seconds: number | null): string {
  if (seconds === null) return "Timing unavailable";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

export function failureDescription(code: string | null): string {
  switch (code) {
    case "provider_unavailable": return "The AI service could not complete this attempt.";
    case "invalid_ai_selection": return "The proposed edit plan did not pass validation.";
    case "source_unavailable": return "Source footage could not be read or verified.";
    case "processing_limit": return "The request exceeded the processing limits.";
    case "worker_lease_expired": return "The processing attempt expired before it finished.";
    default: return "Processing could not finish. No new request has been submitted.";
  }
}
