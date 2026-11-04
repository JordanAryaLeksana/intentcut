"use client";

import { useEditingScope } from "../workflow";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import {
  createCaptionSet,
  exportCaptions,
  getCaptionSet,
  getVideoCaptions,
  saveCaptionSet,
  transcribeVideo,
  type CaptionJob,
  type CaptionSet,
  type VideoCaptions,
} from "@/lib/api/captions";
import { listAIArtifacts } from "@/lib/api/artifacts";
import { usePreviewJob } from "../use-editing";
import { useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";
import {
  STAGE_COPY,
  failureDescription,
} from "../ai-director/processing-state";
import {
  captionDirty,
  captionScope,
  useCaptionStore,
  type CaptionDraft,
} from "./store";

export const videoCaptionsKey = (project: string, video: string) =>
  ["projects", project, "video-captions", video] as const;
export function captionPolling(data?: VideoCaptions): number | false {
  return data?.jobs.some((j) => j.status === "queued" || j.status === "running")
    ? 2000
    : false;
}
function message(error: unknown) {
  if (error instanceof ApiError && error.status === 409)
    return "Your captions changed elsewhere. Your words here are kept — reload only if you want to discard them.";
  return error instanceof Error
    ? error.message
    : "We couldn’t confirm that. Check again before trying once more.";
}
function CaptionJobStatus({
  project,
  job,
}: {
  project: string;
  job: CaptionJob;
}) {
  const status = useAIJobStatus(project, job.id);
  const value = status.data?.status ?? job.status;
  const title =
    job.kind === "caption_transcribe_v1"
      ? "Captions from speech"
      : `${job.enabled_cues === 0 ? "Video without captions" : "Video with captions"} · Version ${job.caption_revision}`;
  return (
    <div role="status" className="studio-captionJob">
      <strong>{title}</strong>:{" "}
      {value === "queued"
        ? "Waiting to start"
        : value === "running"
          ? status.data?.progress?.stage === "publishing_artifacts"
            ? "Saving your captioned video"
            : STAGE_COPY[status.data?.progress?.stage ?? "preparing_media"]
                .title
          : value === "succeeded"
            ? "Ready"
            : failureDescription(status.data?.error_code ?? job.error_code)}
      {status.isError && (
        <>
          <span> We couldn’t check progress.</span>
          <button type="button" onClick={() => void status.refetch()}>
            Check again
          </button>
        </>
      )}
    </div>
  );
}
export function CaptionFields({
  draft,
  saving = false,
  exporting = false,
  onChange,
  onSave,
  onExport,
}: {
  draft: CaptionDraft;
  saving?: boolean;
  exporting?: boolean;
  onChange: (
    index: number,
    patch: Partial<{ text: string; enabled: boolean }>,
  ) => void;
  onSave: () => void;
  onExport: () => void;
}) {
  const dirty = captionDirty(draft);
  return (
    <>
      <p role="status">
        {dirty
          ? "Unsaved caption changes"
          : `Caption version ${draft.saved.revision} saved`}{" "}
        · What you see here is a preview — your video file doesn’t change until
        you export.
      </p>
      {!draft.edits.some((c) => c.enabled) && (
        <p>
          {draft.edits.length
            ? "No captions are turned on."
            : "We didn’t hear any speech in this video."}{" "}
          Exporting will keep your video as it is, without subtitles.
        </p>
      )}
      <ol className="studio-captionCues">
        {draft.edits.map((cue, i) => (
          <li key={cue.index}>
            <div className="studio-captionCueHeader">
              <label>
                <input
                  type="checkbox"
                  checked={cue.enabled}
                  onChange={(e) =>
                    onChange(cue.index, { enabled: e.target.checked })
                  }
                />{" "}
                Caption {i + 1}
              </label>
              <span className="technical">
                {(draft.saved.cues[i].start_ms / 1000).toFixed(1)}–
                {(draft.saved.cues[i].end_ms / 1000).toFixed(1)}s
              </span>
            </div>
            <label
              htmlFor={`caption-text-${draft.saved.id}-${i}`}
              className="sr-only"
            >
              Text for caption {i + 1}
            </label>
            <textarea
              id={`caption-text-${draft.saved.id}-${i}`}
              value={cue.text}
              maxLength={2000}
              rows={3}
              onChange={(e) => onChange(cue.index, { text: e.target.value })}
              aria-invalid={cue.enabled && !cue.text.trim()}
            />
            {cue.enabled && !cue.text.trim() && (
              <p role="alert">Write something, or turn this caption off.</p>
            )}
          </li>
        ))}
      </ol>
      <div className="studio-captionActions">
        <button
          type="button"
          className="button button-secondary"
          disabled={
            !dirty ||
            saving ||
            draft.edits.some((c) => c.enabled && !c.text.trim())
          }
          onClick={() => onSave()}
        >
          {saving ? "Saving…" : "Save captions"}
        </button>
        <button
          type="button"
          className="button button-primary"
          disabled={dirty || saving || exporting}
          onClick={() => onExport()}
        >
          {exporting ? "Creating your video…" : "Export video with captions"}
        </button>
      </div>
    </>
  );
}
export function CaptionEditor({
  project,
  video,
  saved,
  onRefresh,
}: {
  project: string;
  video: string;
  saved: CaptionSet;
  onRefresh: () => void;
}) {
  const scope = captionScope(project, video, saved.id);
  const draft = useCaptionStore((state) => state.drafts[scope]);
  const { receive, change, saved: markSaved } = useCaptionStore();
  const [reloadError, setReloadError] = useState<string | null>(null);
  useEffect(() => receive(scope, saved), [scope, saved, receive]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("Caption draft unavailable.");
      return saveCaptionSet(
        project,
        draft.saved.id,
        draft.saved.revision,
        draft.edits,
      );
    },
    retry: false,
    onSuccess: (result) => {
      markSaved(scope, result);
      onRefresh();
    },
  });
  const exportJob = useMutation({
    mutationFn: async () => {
      if (!draft || captionDirty(draft))
        throw new Error("Save captions before exporting.");
      return exportCaptions(project, draft.saved.id, draft.saved.revision);
    },
    retry: false,
    onSuccess: onRefresh,
  });
  if (!draft) return <p role="status">Loading your captions…</p>;
  async function reload() {
    try {
      receive(scope, await getCaptionSet(project, saved.id), true);
      save.reset();
      setReloadError(null);
      onRefresh();
    } catch {
      setReloadError(
        "We couldn’t reload your captions. What you wrote here is still kept.",
      );
    }
  }
  return (
    <div className="studio-captionEditor">
      <CaptionFields
        draft={draft}
        saving={save.isPending}
        exporting={exportJob.isPending}
        onChange={(index, patch) => change(scope, index, patch)}
        onSave={() => save.mutate()}
        onExport={() => exportJob.mutate()}
      />
      {save.isError && (
        <div role="alert">
          <p>{message(save.error)}</p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reload()}
          >
            Discard local changes and reload saved captions
          </button>
        </div>
      )}
      {exportJob.isError && <p role="alert">{message(exportJob.error)}</p>}
      {reloadError && <p role="alert">{reloadError}</p>}
    </div>
  );
}
function VideoCaptionsPanel({
  project,
  video,
}: {
  project: string;
  video: string;
}) {
  const { scope: workflowKey } = useEditingScope(project);
  const client = useQueryClient();
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const state = useQuery({
    queryKey: videoCaptionsKey(project, video),
    queryFn: ({ signal }) => getVideoCaptions(project, video, signal),
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (q) =>
      q.state.error ? false : captionPolling(q.state.data),
  });
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: videoCaptionsKey(project, video),
    });
  };
  const [requestId] = useState(() => crypto.randomUUID());
  const [previewError, setPreviewError] = useState<string | null>(null);
  const setPreview = useCaptionStore((s) => s.preview);
  const transcribe = useMutation({
    mutationFn: () => transcribeVideo(project, video, requestId),
    retry: false,
    onSuccess: refresh,
  });
  const create = useMutation({
    mutationFn: (id: string) => createCaptionSet(project, id),
    retry: false,
    onSuccess: refresh,
  });
  async function preview(job: CaptionJob) {
    try {
      const artifacts = await listAIArtifacts(project, job.id);
      const artifact = artifacts.items.find(
        (a) => a.kind === "rendition" && a.parent_artifact_id === video,
      );
      if (!artifact)
        throw new Error(
          "Your captioned video isn’t ready yet. Check again in a moment.",
        );
      if (!alive.current) return;
      setPreview(workflowKey, {
        jobId: job.id,
        artifactId: artifact.id,
        label: `${job.enabled_cues === 0 ? "Video without captions" : "Video with captions"} · Version ${job.caption_revision}`,
      });
      setPreviewError(null);
    } catch (e) {
      if (alive.current) setPreviewError(message(e));
    }
  }
  if (state.isPending)
    return <p role="status">Loading captions for this video…</p>;
  if (state.isError)
    return (
      <div role="alert">
        <p>
          Captions aren’t available for this video yet. Your video is saved —
          try again in a moment.
        </p>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => void state.refetch()}
        >
          Try again
        </button>
      </div>
    );
  const data = state.data;
  const saved = data.sets[0];
  const transcription = data.jobs.find(
    (j) => j.kind === "caption_transcribe_v1",
  );
  const exports = data.jobs.filter((j) => j.kind === "caption_burn_v1");
  return (
    <>
      <p className="studio-storyboardNote">
        Captions belong to the video version you’re watching. Pick a different
        version above to see its captions.
      </p>
      {!transcription && !data.transcriptions.length && (
        <>
          <p>
            We’ll listen to your video and write down what’s said. This may use
            paid credits.
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={transcribe.isPending}
            onClick={() => transcribe.mutate()}
          >
            {transcribe.isPending
              ? "Creating captions…"
              : "Create captions from speech"}
          </button>
        </>
      )}
      {transcribe.isError && (
        <p role="alert">
          {message(transcribe.error)}{" "}
          <button type="button" onClick={() => void state.refetch()}>
            Check what’s already done
          </button>
        </p>
      )}
      {transcription && (
        <CaptionJobStatus project={project} job={transcription} />
      )}
      {!saved && data.transcriptions[0] && (
        <button
          type="button"
          className="button button-secondary"
          disabled={create.isPending}
          onClick={() => create.mutate(data.transcriptions[0].id)}
        >
          {create.isPending ? "Opening captions…" : "Edit captions"}
        </button>
      )}
      {create.isError && <p role="alert">{message(create.error)}</p>}
      {saved && (
        <CaptionEditor
          key={saved.id}
          project={project}
          video={video}
          saved={saved}
          onRefresh={refresh}
        />
      )}
      {exports.map((job) => (
        <div key={job.id} className="studio-captionOutput">
          <CaptionJobStatus project={project} job={job} />
          {job.status === "succeeded" && (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void preview(job)}
            >
              Watch / download{" "}
              {job.enabled_cues === 0
                ? "video without captions"
                : "video with captions"}{" "}
              · Version {job.caption_revision}
            </button>
          )}
        </div>
      ))}
      {previewError && <p role="alert">{previewError}</p>}
    </>
  );
}
function ConnectedCaptionsPanel({ projectId }: { projectId: string }) {
  const { scope } = useEditingScope(projectId);
  const { jobId: base } = usePreviewJob(projectId ?? "");
  const override = useCaptionStore((s) =>
    projectId ? s.previews[scope] : undefined,
  );
  const jobId = override?.jobId ?? base;
  const artifacts = useAIArtifacts(projectId ?? "", jobId);
  const video = artifacts.data?.items.find((a) =>
    override ? a.id === override.artifactId : a.kind === "video",
  );
  return (
    <section className="studio-captions" aria-labelledby="captions-heading">
      <header className="studio-panelHeader">
        <h2 id="captions-heading">Captions</h2>
        <span>Subtitles for this video</span>
      </header>
      <div className="studio-captionBody">
        {!projectId ? (
          <p>Open a project to work with captions.</p>
        ) : artifacts.isError ? (
          <p role="alert">
            We couldn’t load your video.{" "}
            <button type="button" onClick={() => void artifacts.refetch()}>
              Try again
            </button>
          </p>
        ) : !video ? (
          <p>Choose a finished video in Preview &amp; Export first.</p>
        ) : (
          <VideoCaptionsPanel
            key={`${projectId}:${video.id}`}
            project={projectId}
            video={video.id}
          />
        )}
      </div>
    </section>
  );
}

export function CaptionsPanel({ projectId }: { projectId?: string }) {
  return projectId ? (
    <ConnectedCaptionsPanel key={projectId} projectId={projectId} />
  ) : (
    <section className="studio-captions">
      <header className="studio-panelHeader">
        <h2>Captions</h2>
      </header>
      <p>Open a project to work with captions.</p>
    </section>
  );
}
