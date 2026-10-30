
"use client";

import {
  MAX_PREVIEW_BYTES,
  useVideoArtifact,
} from "./hooks/use-video-artifact";

interface VideoArtifactPlayerProps {
  projectId: string;
  jobId: string;
  artifactId: string;
  sizeBytes: number;
}

export function VideoArtifactPlayer({
  projectId,
  jobId,
  artifactId,
  sizeBytes,
}: VideoArtifactPlayerProps) {
  const { preview, load, cancel } = useVideoArtifact(
    projectId,
    jobId,
    artifactId,
    sizeBytes,
  );

  const previewAllowed =
    Number.isSafeInteger(sizeBytes) &&
    sizeBytes > 0 &&
    sizeBytes <= MAX_PREVIEW_BYTES;

  return (
    <div className="studio-player space-y-3">
      {!previewAllowed && (
        <p className="text-xs text-muted-foreground">
          This video is too large for browser preview.
          The maximum preview size is 100 MiB.
        </p>
      )}

      {preview.status === "idle" && previewAllowed && (
        <button
          type="button"
          className="button button-secondary"
          onClick={() => void load()}
        >
          Load MP4 preview
        </button>
      )}

      {preview.status === "loading" && (
        <div className="space-y-2">
          <p role="status" className="text-xs">
            Downloading generated video...
          </p>

          <button
            type="button"
            className="button button-secondary"
            onClick={cancel}
          >
            Cancel loading
          </button>
        </div>
      )}

      {preview.status === "error" && (
        <div className="space-y-2">
          <p role="alert" className="media-errors">
            {preview.message}
          </p>

          {previewAllowed && (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void load()}
            >
              Retry preview
            </button>
          )}
        </div>
      )}

      {preview.status === "ready" && (
        <div className="studio-playerReady space-y-3">
          <video
            controls
            playsInline
            preload="metadata"
            src={preview.url}
            className="w-full rounded-lg bg-black"
            aria-label="Rendered first cut"
          >
            Your browser does not support MP4 playback.
          </video>

          <a
            href={preview.url}
            download={`intentcut-first-cut-${artifactId}.mp4`}
            className="button button-primary"
          >
            Download MP4
          </a>
        </div>
      )}
    </div>
  );
}
