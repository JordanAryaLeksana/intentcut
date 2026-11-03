"use client";

import { formatBytes } from "../media/selection";
import { useAIArtifacts } from "./hooks/use-ai-artifacts";
import { StoryboardViewer } from "./storyboard/storyboard-viewer";
interface JobArtifactsProps {
  projectId: string;
  jobId: string;
}
export function JobArtifacts({ projectId, jobId }: JobArtifactsProps) {
  const artifacts = useAIArtifacts(projectId, jobId);

  if (artifacts.isPending) {
    return (
      <p role="status" className="mt-3 text-sm">
        Loading what we made for you…
      </p>
    );
  }

  if (artifacts.isError) {
    return (
      <div className="mt-3 space-y-2">
        <p role="alert" className="media-errors">
          We couldn’t load your video and story plan. Your work is saved — try again.
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void artifacts.refetch()}
        >
          Try again
        </button>
      </div>
    );
  }

  const items = artifacts.data.items;

  return (
    <div className="mt-4 space-y-3">
      <h5 className="text-sm font-medium">What we made for you</h5>

      {items.length === 0 ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Your video finished, but nothing came back to show. Check again — don’t create another cut yet.
          </p>

          <button
            type="button"
            className="button button-secondary"
            onClick={() => void artifacts.refetch()}
          >
            Check again
          </button>
        </div>
      ) : (
        <ul className="space-y-2" aria-label="What we made for you">
          {items.map((artifact) => (
            <li
              key={artifact.id}
              className="rounded-lg border border-current/20 p-3"
            >
              <p className="text-sm font-medium">{artifact.kind === "video" ? "Your video" : artifact.kind === "storyboard" ? "Story plan" : "Your file"}</p>

              <p className="mt-1 text-xs text-muted-foreground">
                {formatBytes(artifact.size_bytes)}
              </p>

              {artifact.kind === "storyboard" && (
                <StoryboardViewer
                  projectId={projectId}
                  jobId={jobId}
                  artifactId={artifact.id}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
