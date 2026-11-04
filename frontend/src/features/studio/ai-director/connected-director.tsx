"use client";

import { useRef, type FormEvent } from "react";
import { RevisionChat } from "./revision-chat";
import { useEditableFirstCut } from "./hooks/use-editable-first-cut";
import { DirectorProcessingStatus } from "./director-processing-status";
import { useDirectorForm } from "./hooks/use-director-hook-form";

interface ConnectedDirectorProps {
  projectId: string;
}

export function ConnectedDirector({ projectId }: ConnectedDirectorProps) {
  const director = useDirectorForm(projectId);
  const editable = useEditableFirstCut(
    projectId,
    director.jobId,
    director.jobs,
  );
  const intentField = useRef<HTMLTextAreaElement>(null);

 const hasEditableFirstCut = Boolean(editable);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Prevent accidental new First Cut creation.
    if (hasEditableFirstCut || !director.canSubmit) {
      return;
    }

    void director.submit();
  }

  return (
    <div className="studio-directorBody">
      <DirectorProcessingStatus projectId={projectId} firstCutJobId={director.jobId}>
        {director.failed && (
          <p className="text-sm text-muted-foreground">
            Your previous First Cut didn’t finish. Review your footage and
            story instructions below, then click Retry First Cut to generate
            a new video.
          </p>
        )}
      </DirectorProcessingStatus>

      {!hasEditableFirstCut && (
      <details
        className="processing-request"
        open={!director.jobId || director.inputsMissing}
      >
        <summary>Create Your First Cut</summary>
        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div className="space-y-2">
            <label
              htmlFor="creative-intent"
              className="block text-sm font-medium"
            >
              Your story idea
            </label>

            <textarea
              ref={intentField}
              id="creative-intent"
              required
              minLength={1}
              maxLength={1000}
              rows={5}
              value={director.intent}
              disabled={director.formDisabled}
              onChange={(event) => director.setIntent(event.target.value)}
              placeholder="Create a cinematic travel recap..."
              className="w-full resize-y rounded-lg border border-current/30 bg-transparent p-3 text-sm"
            />

            <p className="text-xs text-muted-foreground">
              {director.intent.length}/1000 characters
            </p>
          </div>

          <div className="space-y-2">
            <label
              htmlFor="target-duration"
              className="block text-sm font-medium"
            >
              How long should it be? (seconds)
            </label>

            <input
              id="target-duration"
              type="number"
              min="1"
              max="120"
              step="1"
              required
              value={director.duration}
              disabled={director.formDisabled}
              onChange={(event) => director.setDuration(event.target.value)}
              className="w-full rounded-lg border border-current/30 bg-transparent p-3 text-sm"
            />
          </div>

          <p role="status" className="studio-availability">
            {director.selectedCount} saved video
            {director.selectedCount === 1 ? "" : "s"} selected.
          </p>

          {!director.selectionValid && (
            <p className="text-xs text-muted-foreground">
              {director.mediaLoading
                ? "Checking your footage…"
                : "Pick footage in Media Library first — tick “Use in my first cut”."}
            </p>
          )}

          {director.mediaError && (
            <p role="alert" className="media-errors">
              We couldn’t check your footage. Your picks are kept — try again.
            </p>
          )}

          {!hasEditableFirstCut && (
            <button
              type="submit"
              className="button button-primary"
              disabled={!director.canSubmit}
            >
              {director.isSubmitting
                ? "Creating your first cut…"
                : director.failed
                  ? "Retry First Cut"
                  : "Create First Cut"}
            </button>
          )}
        </form>
      </details>
      )}
      {director.submitError && (
        <p role="alert" className="media-errors mt-4">
          We couldn’t confirm a new First Cut. Check the processing status
          before trying again.
        </p>
      )}

      {(director.uncertain || director.recoveryError) && (
        <div className="media-errors mt-3" role="alert">
          <p>
            {director.uncertain
              ? "Your First Cut may already have started. Submissions are paused until we can find it. Check again shortly."
              : "We couldn’t check your previous First Cuts. Check again before starting a new one."}
          </p>
          <button
            type="button"
            className="button button-secondary mt-2"
            onClick={() => void director.checkRecovery()}
          >
            Check processing status
          </button>
        </div>
      )}

      {editable && (
        <div className="mt-6">
          <RevisionChat key={projectId} projectId={projectId} />
        </div>
      )}
    </div>
  );
}
