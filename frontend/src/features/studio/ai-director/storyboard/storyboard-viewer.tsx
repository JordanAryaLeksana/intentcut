
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
        {expanded ? "Hide storyboard" : "View storyboard"}
      </button>

      {expanded && storyboard.isPending && (
        <p role="status">Loading storyboard...</p>
      )}

      {expanded && storyboard.isError && (
        <div className="space-y-2">
          <p role="alert" className="media-errors">
            {storyboard.error instanceof Error
              ? storyboard.error.message
              : "Unable to load storyboard."}
          </p>

          <button
            type="button"
            className="button button-secondary"
            onClick={() => void storyboard.refetch()}
          >
            Retry
          </button>
        </div>
      )}

      {expanded && storyboard.data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Target</p>
              <p>{formatSeconds(storyboard.data.target_seconds)}</p>
            </div>

            <div>
              <p className="text-muted-foreground">Planned cuts</p>
              <p>{formatSeconds(storyboard.data.total_seconds)}</p>
            </div>

            {storyboard.data.render_seconds !== undefined && (
              <div>
                <p className="text-muted-foreground">Render duration</p>
                <p>{formatSeconds(storyboard.data.render_seconds)}</p>
              </div>
            )}

            <div>
              <p className="text-muted-foreground">Cut count</p>
              <p>{storyboard.data.cuts.length}</p>
            </div>
          </div>

          <ol className="space-y-3" aria-label="Storyboard cuts">
            {storyboard.data.cuts.map((cut, index) => (
              <li
                key={cut.window_index}
                className="rounded-lg border border-current/20 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <h5 className="text-sm font-medium">
                    Cut {String(index + 1).padStart(2, "0")}
                  </h5>

                  <span className="text-xs text-muted-foreground">
                    {formatSeconds(
                      cut.end_seconds - cut.start_seconds,
                    )}
                  </span>
                </div>

                <p className="mt-2 text-xs">
                  Source range:{" "}
                  {formatSeconds(cut.start_seconds)}
                  {" – "}
                  {formatSeconds(cut.end_seconds)}
                </p>

                <p className="mt-1 text-xs text-muted-foreground">
                  Window index: {cut.window_index}
                </p>

                {cut.source_window_index !== undefined && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Source window: {cut.source_window_index}
                  </p>
                )}

                {cut.playback_order !== undefined && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Playback order: {cut.playback_order}
                  </p>
                )}

                {cut.media_id && (
                  <p className="mt-2 break-all text-xs text-muted-foreground">
                    Media ID: {cut.media_id}
                  </p>
                )}
              </li>
            ))}
          </ol>

          <p className="text-xs text-muted-foreground">
            Source ranges and cut metadata come from
            the published storyboard. Exact synchronization
            with the rendered MP4 is not available yet.
          </p>
        </div>
      )}
    </div>
  );
}
