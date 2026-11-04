"use client";

import { useEffect, useRef } from "react";
import { ApiError } from "@/lib/api/transport";
import { useCaptionStore } from "./captions/store";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { renderDraft } from "@/lib/api/editing";
import {
  draftMatchesSaved,
  useDraftStore,
  type TimelineDraft,
} from "./store/use-draft-store";
import {
  renderVersionsKey,
  useRenderVersions,
  usePreviewJob,
} from "./use-editing";
import { aiJobKey } from "./ai-director/hooks/use-ai-job-status";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";
import { failureDescription } from "./ai-director/processing-state";

export function renderSummary(status: string): string {
  switch (status) {
    case "queued": return "Queued · Waiting for the manual render worker";
    case "running": return "Rendering · Creating your video…";
    case "succeeded": return "Ready · Your finished video is ready to watch";
    case "failed": return "Failed · Try making this video again";
    default: return "Checking video status…";
  }
}

function ManualRenderStatus({
  projectId,
  jobId,
  revision,
  listedStatus,
}: {
  projectId: string;
  jobId: string;
  revision: number;
  listedStatus: string;
}) {
  const job = useAIJobStatus(projectId, jobId);
  const client = useQueryClient();
  useEffect(() => {
    if (job.data && job.data.status !== listedStatus) {
      void client.invalidateQueries({ queryKey: renderVersionsKey(projectId) });
    }
  }, [client, projectId, job.data, listedStatus]);
  if (job.isError)
    return (
      <p role="alert">
        We couldn’t check on your video.{" "}
        <button type="button" onClick={() => void job.refetch()}>
          Check again
        </button>
      </p>
    );
  const status = job.data?.status;
  const stage = job.data?.progress?.stage;
  const labels: Record<string, string> = {
    preparing_media: "Getting your footage ready",
    extracting_windows: "Finding the moments to use",
    rendering_video: "Putting your video together",
    publishing_artifacts: "Saving your video",
  };
  return (
    <p role="status">
      Version {revision}:{" "}
      {status === "queued"
        ? "Queued · Waiting for the manual render worker"
        : status === "running"
          ? `Rendering · ${labels[stage ?? ""] ?? "Creating your video"}`
          : status === "succeeded"
            ? "Ready · Your video is ready"
            : status === "failed"
              ? `Failed · ${failureDescription(job.data?.error_code ?? null)}`
              : "Checking on your video"}
    </p>
  );
}

export function DraftPersistence({
  projectId,

  draft,
}: {
  projectId: string;
  draft: TimelineDraft;
}) {
  const client = useQueryClient();
  const renderLock = useRef(false);
  const saved = useDraftStore((state) => state.savedByProject[projectId]);
  const { setPreview } = useDraftStore();
  const versions = useRenderVersions(projectId);
  const matches = draftMatchesSaved(draft, saved);
  const currentRender = versions.data?.find(
    (v) => v.revision === saved?.revision,
  );
  const render = useMutation({
    mutationFn: async () => {
      if (!saved || !matches)
        throw new Error("Save this draft before making your video.");
      const revision = saved.revision;
      await client.cancelQueries({ queryKey: renderVersionsKey(projectId) });
      return { jobId: await renderDraft(projectId, revision), revision };
    },
    retry: false,
    onSuccess: async ({ jobId, revision }) => {
      client.setQueryData<import("@/lib/api/editing").RenderVersion[]>(renderVersionsKey(projectId), previous =>
        previous?.some(v => v.job_id === jobId) ? previous : [{ job_id: jobId, revision, status: "queued" }, ...(previous ?? [])]);
      useCaptionStore.getState().preview(projectId);
      setPreview(projectId, jobId);
      void client.invalidateQueries({ queryKey: aiJobKey(projectId, jobId) });
      await client.invalidateQueries({ queryKey: renderVersionsKey(projectId) });
    },
    onSettled: () => { renderLock.current = false; },
  });
  return (
    <div className="studio-draftPersistence">
      <p role="status">
        {matches
          ? `Saved as version ${saved?.revision}`
          : "You have unsaved changes"}{" "}
        ·{" "}
        {render.isPending ? "Requesting your video…" : currentRender ? renderSummary(currentRender.status)
          : versions.isPending ? "Checking video versions…" : versions.isError ? "Video status unavailable · Check versions below"
          : "You haven’t made a video from this draft yet"}
      </p>
      <div className="studio-draftActions">
        {!matches && (
          <a
            href="#editing-draft-save"
            className="studio-toolbarLink"
            onClick={(event) => {
              event.preventDefault();
              useDraftStore.getState().setDockTab(projectId, "director");
              requestAnimationFrame(() => {
                const target = document.getElementById("editing-draft-save");
                target?.scrollIntoView({ block: "center" });
                target?.focus({ preventScroll: true });
              });
            }}
          >
            Save your draft in AI Director → Rework your story
          </a>
        )}
        <button
          type="button"
          className="button button-primary"
          disabled={
            !matches ||
            !draft.cuts.length ||
            render.isPending ||
            currentRender?.status === "queued" ||
            currentRender?.status === "running" ||
            currentRender?.status === "succeeded"
          }
          onClick={() => {
            if (renderLock.current || render.isPending || !matches) return;
            renderLock.current = true;
            render.mutate();
          }}
        >
          {render.isPending
            ? "Creating your video…"
            : currentRender?.status === "failed"
              ? "Try making this video again"
              : "Make my video"}
        </button>
      </div>
      {render.isError && (
        <p role="alert">
          {render.error instanceof ApiError && render.error.status === 409 ? "Your saved draft changed. Reload the saved draft before rendering." : "We couldn’t confirm the render request. Check versions, then retry Make my video if needed."}{" "}
          <button type="button" onClick={() => void versions.refetch()}>
            Check versions
          </button>
        </p>
      )}
      {versions.isError && (
        <p role="alert">
          We couldn’t load your video versions.{" "}
          <button type="button" onClick={() => void versions.refetch()}>
            Try again
          </button>
        </p>
      )}
      {currentRender && (
        <ManualRenderStatus
          projectId={projectId}
          jobId={currentRender.job_id}
          revision={currentRender.revision}
          listedStatus={currentRender.status}
        />
      )}
    </div>
  );
}

export function RenderVersionPicker({ projectId }: { projectId: string }) {
  const { manual, versions } = usePreviewJob(projectId);
  const captioned = useCaptionStore((state) => state.previews[projectId]);
  const clearCaptioned = useCaptionStore((state) => state.preview);
  const setPreview = useDraftStore((state) => state.setPreview);
  return (
    <label className="studio-renderPicker">
      Choose a version to watch{" "}
      <select
        value={
          captioned
            ? `captioned:${captioned.artifactId}`
            : (manual?.job_id ?? "")
        }
        onChange={(event) => {
          if (event.target.value.startsWith("captioned:")) return;
          clearCaptioned(projectId);
          setPreview(projectId, event.target.value || null);
        }}
      >
        {captioned && (
          <option value={`captioned:${captioned.artifactId}`}>
            {captioned.label}
          </option>
        )}
        <option value="">Your first cut</option>
        {versions.data?.map((v) => (
          <option key={v.job_id} value={v.job_id}>
            Version {v.revision} ·{" "}
            {v.status === "succeeded" ? "ready" : v.status}
          </option>
        ))}
      </select>
    </label>
  );
}
