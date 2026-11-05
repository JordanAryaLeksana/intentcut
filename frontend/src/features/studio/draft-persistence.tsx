"use client";

import { useEditingScope } from "./workflow";

import { useEffect, useRef } from "react";
import { ApiError } from "@/lib/api/transport";
import { useCaptionStore } from "./captions/store";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { renderDraft } from "@/lib/api/editing";
import {
  draftMatchesSaved,
  draftSyncState,
  isDraftDirty,
  useDraftStore,
  type TimelineDraft,
} from "./store/use-draft-store";
import {
  pendingRevisionNotices,
  proposalOptions,
  REVISION_NOTICE_COPY,
  useRevisionInstruction,
} from "./ai-director/revision-chat";
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
    case "queued": return "Queued · Waiting to start";
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
  const { workflow } = useEditingScope(projectId);
  const job = useAIJobStatus(projectId, jobId);
  const client = useQueryClient();
  useEffect(() => {
    if (job.data && job.data.status !== listedStatus) {
      void client.invalidateQueries({ queryKey: renderVersionsKey(projectId, workflow) });
    }
  }, [workflow, client, projectId, job.data, listedStatus]);
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
        ? "Queued · Waiting to start"
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
  const { workflow, scope } = useEditingScope(projectId);
  const client = useQueryClient();
  const renderLock = useRef(false);
  const saved = useDraftStore((state) => state.savedByProject[scope]);
  const clearPreviewSelection = useDraftStore((state) => state.clearPreviewSelection);
  const versions = useRenderVersions(projectId);
  const proposals = useQuery(proposalOptions(projectId, workflow));
  const unsentInstruction = useRevisionInstruction((state) => state.byScope[scope]);
  const unconfirmed = useRevisionInstruction((state) => Boolean(state.unconfirmedByScope[scope]));
  const notices = pendingRevisionNotices(unsentInstruction, proposals.data, unconfirmed);
  const matches = draftMatchesSaved(draft, saved);
  const sync = draftSyncState(draft, saved);
  // A saved order identical to the generated one renders the same video.
  const sameAsOriginal = sync === "saved" && !isDraftDirty(draft);
  const currentRender = versions.data?.find(
    (v) => v.revision === saved?.revision,
  );
  const render = useMutation({
    mutationFn: async () => {
      if (!saved || !matches)
        throw new Error("Save this draft before making your video.");
      const revision = saved.revision;
      await client.cancelQueries({ queryKey: renderVersionsKey(projectId, workflow) });
      return { jobId: await renderDraft(projectId, revision, workflow), revision };
    },
    retry: false,
    onSuccess: async ({ jobId, revision }) => {
      client.setQueryData<import("@/lib/api/editing").RenderVersion[]>(renderVersionsKey(projectId, workflow), previous =>
        previous?.some(v => v.job_id === jobId) ? previous : [{ job_id: jobId, revision, status: "queued" }, ...(previous ?? [])]);
      useCaptionStore.getState().preview(scope);
      // Keep the playable video on screen while the new version renders. The
      // monitor follows the newest *ready* version automatically, so it
      // switches to this render only once it has succeeded.
      clearPreviewSelection(scope);
      void client.invalidateQueries({ queryKey: aiJobKey(projectId, jobId) });
      await client.invalidateQueries({ queryKey: renderVersionsKey(projectId, workflow) });
    },
    onSettled: () => { renderLock.current = false; },
  });
  return (
    <div className="studio-draftPersistence">
      <p role="status">
        {sync === "original"
          ? "No edits yet · Your current video already uses this order"
          : <>
            {matches
              ? `Saved as version ${saved?.revision}`
              : "You have unsaved changes"}{" "}
            ·{" "}
            {render.isPending ? "Requesting your video…" : currentRender ? renderSummary(currentRender.status)
              : versions.isPending ? "Checking video versions…" : versions.isError ? "Video status unavailable · Check versions below"
              : "You haven’t made a video from this draft yet"}
          </>}
      </p>
      {sameAsOriginal && !currentRender && (
        <p className="studio-draftNotice">This saved version has the same order as your original video, so a new video would look the same.</p>
      )}
      {notices.map((notice) => (
        <p key={notice} className="studio-draftNotice" data-notice={notice}>{REVISION_NOTICE_COPY[notice]}</p>
      ))}
      <div className="studio-draftActions">
        {sync === "unsaved" && (
          <a
            href={(workflow === "first_cut" ? "#editing-draft-save" : "#editing-draft-save-highlights")}
            className="studio-toolbarLink"
            onClick={(event) => {
              event.preventDefault();
              useDraftStore.getState().setDockTab(scope, workflow === "highlights" ? "highlights" : "director");
              requestAnimationFrame(() => {
                const target = document.getElementById((workflow === "first_cut" ? "editing-draft-save" : "editing-draft-save-highlights"));
                target?.scrollIntoView({ block: "center" });
                target?.focus({ preventScroll: true });
              });
            }}
          >
            Save your draft in Rework your story
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
  const { workflow, scope } = useEditingScope(projectId);
  const { manual, versions } = usePreviewJob(projectId);
  const captioned = useCaptionStore((state) => state.previews[scope]);
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
          clearCaptioned(scope);
          setPreview(scope, event.target.value || null);
        }}
      >
        {captioned && (
          <option value={`captioned:${captioned.artifactId}`}>
            {captioned.label}
          </option>
        )}
        <option value="">{workflow === "highlights" ? "Your highlights" : "Your first cut"}</option>
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
