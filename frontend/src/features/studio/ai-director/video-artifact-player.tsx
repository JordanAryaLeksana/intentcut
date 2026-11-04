
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
  autoLoad?: boolean;
}

export function VideoArtifactPlayer({
  projectId,
  jobId,
  artifactId,
  sizeBytes,
  autoLoad = false,
}: VideoArtifactPlayerProps) {
  const { preview, load, cancel } = useVideoArtifact(
    projectId,
    jobId,
    artifactId,
    sizeBytes,
  );

  useEffect(() => {
    let active = true;
    // Defer until mount effects settle so Strict Mode's discarded mount cannot
    // start a duplicate download. No delay or polling is involved.
    void Promise.resolve().then(() => {
      if (active && autoLoad && sizeBytes > 0 && sizeBytes <= MAX_PREVIEW_BYTES) void load();
    });
    return () => { active = false; };
  }, [autoLoad, sizeBytes, load]);

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
          Watch your video
        </button>
      )}

      {preview.status === "loading" && (
        <div className="space-y-2">
          <p role="status" className="text-xs">
            Bringing your video here…
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
              Try watching again
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
            aria-label="Your finished video"
          >
            Your browser can’t play this video here.
          </video>

          {draft && <p className="studio-storyboardNote">You’re previewing captions live — they aren’t in the video file yet. Export a video with captions in Captions to keep them.</p>}
          <a
            href={preview.url}
            download={`intentcut-render-${artifactId}.mp4`}
            className="button button-primary"
          >
            Download your video
          </a>
        </div>
      )}
    </div>
  );
}
