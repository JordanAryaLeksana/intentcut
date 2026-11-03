
"use client";

import { useState } from "react";

import { usePublicStoryboard } from "../hooks/use-public-storyboard";

interface StoryboardViewerProps {
  projectId: string;
  jobId: string;
  artifactId: string;
}

function formatSeconds(value: number): string {
  return `${value.toFixed(2)}s`;
}

export function StoryboardViewer({
  projectId,
  jobId,
  artifactId,
}: StoryboardViewerProps) {
  const [expanded, setExpanded] = useState(false);

  const storyboard = usePublicStoryboard(
    projectId,
    jobId,
    artifactId,
    expanded,
  );

  return (
    <div className="mt-3 space-y-3">
      <button
        type="button"
        className="button button-secondary"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Hide story plan" : "See story plan"}
      </button>

      {expanded && storyboard.isPending && (
        <p role="status">Loading your story plan…</p>
      )}

      {expanded && storyboard.isError && (
        <div className="space-y-2">
          <p role="alert" className="media-errors">
            We couldn’t load your story plan. Your video is saved — try again.
          </p>

          <button
            type="button"
            className="button button-secondary"
            onClick={() => void storyboard.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {expanded && storyboard.data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">You asked for</p>
              <p>{formatSeconds(storyboard.data.target_seconds)}</p>
            </div>

            <div>
              <p className="text-muted-foreground">Your story so far</p>
              <p>{formatSeconds(storyboard.data.total_seconds)}</p>
            </div>

            {storyboard.data.render_seconds !== undefined && (
              <div>
                <p className="text-muted-foreground">Finished video</p>
                <p>{formatSeconds(storyboard.data.render_seconds)}</p>
              </div>
            )}

            <div>
              <p className="text-muted-foreground">Moments</p>
              <p>{storyboard.data.cuts.length}</p>
            </div>
          </div>

          <ol className="space-y-3" aria-label="Your story in order">
            {storyboard.data.cuts.map((cut, index) => (
              <li
                key={cut.window_index}
                className="rounded-lg border border-current/20 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <h5 className="text-sm font-medium">
                    Moment {index + 1}
                  </h5>

                  <span className="text-xs text-muted-foreground">
                    {formatSeconds(
                      cut.end_seconds - cut.start_seconds,
                    )}
                  </span>
                </div>

                <p className="mt-2 text-xs">
                  From your footage:{" "}
                  {formatSeconds(cut.start_seconds)}
                  {" – "}
                  {formatSeconds(cut.end_seconds)}
                </p>

                {cut.playback_order !== undefined && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Plays {cut.playback_order + 1} in your story
                  </p>
                )}
              </li>
            ))}
          </ol>

          <p className="text-xs text-muted-foreground">
            Times show where each moment comes from in your footage.
          </p>
        </div>
      )}
    </div>
  );
}
