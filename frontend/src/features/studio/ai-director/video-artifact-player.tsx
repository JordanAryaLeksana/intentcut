
"use client";

import { useEffect, useRef } from "react";
import { useCaptionStore } from "../captions/store";
import { previewCues } from "../captions/preview";

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

  const videoRef = useRef<HTMLVideoElement>(null);
  const trackRef = useRef<{video: HTMLVideoElement; track: TextTrack} | null>(null);
  const draft = useCaptionStore(state=>state.drafts[state.activeByVideo[`${projectId}:${artifactId}`]]);
  useEffect(()=>{
    const video=videoRef.current;
    if (!video || typeof VTTCue === "undefined") return;
    if (!trackRef.current || trackRef.current.video!==video) trackRef.current={video,track:video.addTextTrack("captions","Caption preview", "")};
    const track=trackRef.current.track;
    if (track.cues) for (const cue of Array.from(track.cues)) track.removeCue(cue);
    for (const cue of previewCues(draft)) track.addCue(new VTTCue(cue.start,cue.end,cue.text));
    track.mode=draft ? "showing" : "disabled";
    return ()=>{track.mode="disabled";if(track.cues) for(const cue of Array.from(track.cues)) track.removeCue(cue);};
  },[draft,preview.status]);

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
            ref={videoRef}
            controls
            playsInline
            preload="metadata"
            src={preview.url}
            className="w-full rounded-lg bg-black"
            aria-label="Rendered video"
          >
            Your browser does not support MP4 playback.
          </video>

          {draft && <p className="studio-storyboardNote">Live caption preview · edits are not burned into this MP4. Use Export Captioned MP4 to create a subtitled version.</p>}
          <a
            href={preview.url}
            download={`intentcut-render-${artifactId}.mp4`}
            className="button button-primary"
          >
            Download MP4
          </a>
        </div>
      )}
    </div>
  );
}
