
"use client";

import type { FormEvent } from "react";

import { RevisionChat } from "./revision-chat";
import { JobStatus } from "./job-status";
import { useDirectorForm } from "./hooks/use-director-hook-form";

interface ConnectedDirectorProps {
  projectId: string;
}

export function ConnectedDirector({
  projectId,
}: ConnectedDirectorProps) {
  const director = useDirectorForm(projectId);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void director.submit();
  }

  return (
    <div className="studio-directorBody">
      {!director.jobId && <>
      <p className="studio-overline">Your story, your direction</p>

      <h3>Direct your first cut.</h3>

      <p>
        Tell your AI Director what you want your footage to say.
        It will shape the story with you.
      </p>
      </>}

      <RevisionChat key={projectId} projectId={projectId} />

      {director.jobId && <JobStatus key={director.jobId} projectId={projectId} jobId={director.jobId} />}

      <details className="processing-request" open={director.jobId ? undefined : true}>
      <summary>Your first cut</summary>
      <form onSubmit={handleSubmit} className="mt-5 space-y-4">
        <div className="space-y-2">
          <label
            htmlFor="creative-intent"
            className="block text-sm font-medium"
          >
            Your story idea
          </label>

          <textarea
            id="creative-intent"
            required
            minLength={1}
            maxLength={1000}
            rows={5}
            value={director.intent}
            disabled={Boolean(director.jobId) || director.isSubmitting}
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
            disabled={Boolean(director.jobId) || director.isSubmitting}
            onChange={(event) => director.setDuration(event.target.value)}
            className="w-full rounded-lg border border-current/30 bg-transparent p-3 text-sm"
          />
        </div>

        <p role="status" className="studio-availability">
          {director.selectedCount} saved video{director.selectedCount === 1 ? "" : "s"} selected.
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

        <button
          type="submit"
          disabled={!director.canSubmit}
          className="button button-primary w-full disabled:opacity-50"
        >
          {director.isSubmitting
            ? "Creating your first cut…"
            : "Create my first cut"}
        </button>
      </form>
      </details>

      {director.submitError && (
        <p role="alert" className="media-errors mt-4">
          {director.submitError instanceof Error
            ? director.submitError.message
            : "We couldn’t start your first cut. Nothing was started — you can try again."}
        </p>
      )}

      {director.uncertain && (
        <div className="media-errors mt-3">
          <p>
            Your first cut may already have started.
            Look for it above before starting again,
            so you don’t pay for the same work twice.
          </p>

          <button
            type="button"
            className="button button-secondary mt-2"
            onClick={director.acknowledgeUncertain}
          >
            I checked — start again
          </button>
        </div>
      )}

      {!director.jobId && (
        <button
          type="button"
          className="mt-4 text-xs underline underline-offset-4"
          onClick={director.resumeLastJob}
        >
          Reopen my last cut
        </button>
      )}
    </div>
  );
}
