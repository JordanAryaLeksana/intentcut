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
        Loading generated artifacts...
      </p>
    );
  }

  if (artifacts.isError) {
    return (
      <div className="mt-3 space-y-2">
        <p role="alert" className="media-errors">
          {artifacts.error instanceof Error
            ? artifacts.error.message
            : "Could not retrieve artifacts."}
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void artifacts.refetch()}
        >
          Retry
        </button>
      </div>
    );
  }

  const items = artifacts.data.items;

  return (
    <div className="mt-4 space-y-3">
      <h5 className="text-sm font-medium">Generated artifacts</h5>

      {items.length === 0 ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Processing succeeded, but no artifacts were returned by the API.
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
        <ul className="space-y-2" aria-label="AI artifacts">
          {items.map((artifact) => (
            <li
              key={artifact.id}
              className="rounded-lg border border-current/20 p-3"
            >
              <p className="text-sm font-medium">{artifact.kind}</p>

              <p className="mt-1 text-xs text-muted-foreground">
                {formatBytes(artifact.size_bytes)}
              </p>

              <p className="mt-1 break-all text-xs text-muted-foreground">
                {artifact.id}
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
