import type { AIJob, AIJobProgress, AIProgressStage } from "@/lib/api/contracts";

export interface ObservedJob extends AIJob {
  /** In-memory observation only; never represented as persisted stage history. */
  lastObservedProgress?: AIJobProgress;
}

export const STAGE_COPY: Record<AIProgressStage, { title: string; description: string }> = {
  discovering_highlights: { title: "Finding moments for your prompt", description: "Sampling frames across your source video." },
  refining_highlights: { title: "Looking closer at promising moments", description: "Comparing more frames around the strongest matches." },
  generating_image: { title: "Creating your image", description: "Creating an image from your idea." },
  validating_image: { title: "Checking your image", description: "Making sure your image looks right." },
  preparing_media: { title: "Getting your footage ready", description: "Checking the footage you chose." },
  extracting_audio: { title: "Listening to your footage", description: "Preparing the sound from your video." },
  transcribing_audio: { title: "Writing down what’s said", description: "Turning the speech in your video into words." },
  validating_transcript: { title: "Checking captions", description: "Checking the words and their timing." },
  extracting_windows: { title: "Finding your best moments", description: "Pulling out the moments worth using." },
  understanding_footage: { title: "Watching your footage", description: "Looking through your footage to understand it." },
  selecting_story: { title: "Choosing your story", description: "Picking the order that tells your story best." },
  revising_sequence: { title: "Reworking your story order", description: "Preparing a new order for you to review." },
  rendering_video: { title: "Putting your video together", description: "Building your video in the order you chose." },
  publishing_artifacts: { title: "Saving your first cut", description: "Saving your story plan and finished video." },
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
    case "no_relevant_highlights": return "No sampled moments matched your prompt clearly enough. Try a more visible event or a narrower source. Brief events between samples may be missed.";
    case "caption_render_unsupported": return "We couldn’t add subtitles to this video. Try a different video format.";
    case "invalid_transcript": return "We couldn’t read the speech clearly enough to continue. Nothing new was started.";
    case "transcription_outcome_unknown": return "We’re not sure whether the captions finished. We didn’t start again, so you won’t be charged twice.";
    case "transcription_rate_limited": return "Caption creation is busy right now. Wait a moment, then try again. We didn’t start again for you.";
    case "provider_unavailable": return "The AI service couldn’t finish this time. Your footage is unchanged — you can try again.";
    case "invalid_ai_selection": return "The story plan didn’t hold together. Try describing your story a little differently.";
    case "source_unavailable": return "We couldn’t read your footage. Check that it still plays, then try again.";
    case "processing_limit": return "This video is longer or larger than we can handle in one go. Try a shorter selection.";
    case "worker_lease_expired": return "This try took too long and stopped. Your footage is unchanged — you can try again.";
    default: return "We couldn’t finish your video. Nothing new was started — you can try again.";
  }
}
