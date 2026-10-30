/** Contracts mirrored from the verified IntentCut FastAPI project, media, job and artifact routes. */
export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface MediaAsset {
  id: string;
  project_id: string;
  original_filename: string;
  size_bytes: number;
  duration_seconds: number;
  created_at: string;
  video: {
    stream_index: number;
    codec: string;
    width: number;
    height: number;
    pixel_format: string;
    frame_rate: { numerator: number; denominator: number };
  };
  audio: {
    stream_index: number;
    codec: string;
    sample_rate: number;
    channels: number;
  } | null;
}

export interface MediaList {
  items: MediaAsset[];
  limit: number;
  offset: number;
}

export interface MediaUploadResponse {
  items: MediaAsset[];
}

/** Only request fields accepted by FirstCutRequest; no server-only fingerprints. */
export interface FirstCutRequest {
  kind: "first_cut";
  intent: string;
  target_seconds: number;
  media_ids: string[];
}

export interface AIJobAccepted {
  id: string;
  status: "queued";
  status_url: string;
}

export type AIJobStatus = "queued" | "running" | "succeeded" | "failed";

export type AIProgressStage =
  | "generating_image" | "validating_image"
  | "preparing_media"
  | "extracting_audio" | "transcribing_audio" | "validating_transcript" | "extracting_windows"
  | "understanding_footage"
  | "selecting_story"
  | "revising_sequence"
  | "rendering_video"
  | "publishing_artifacts";

export interface AIJobProgress {
  stage: AIProgressStage;
  stage_started_at: string;
  updated_at: string;
  completed_windows?: number | null;
  total_windows?: number | null;
}

export interface AIJob {
  id: string;
  status: AIJobStatus;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempt_count: number;
  error_code: string | null;
  /** Optional for historical API responses; null when no active stage is known. */
  progress?: AIJobProgress | null;
}

/** Artifact kind remains a string until the backend literal/enum is confirmed. */
export interface AIArtifact {
  parent_artifact_id?: string;
  parent_sha256?: string;
  caption_set_id?: string;
  caption_revision?: number;
  id: string;
  kind: string;
  size_bytes: number;
  download_url: string;
}

export interface AIArtifactList {
  items: AIArtifact[];
}
