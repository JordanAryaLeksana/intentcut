"use client";

import { useEditingScope } from "../workflow";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText } from "./error-handler";
import { downloadAIArtifact } from "@/lib/api/artifacts";
import {
  getVisualHistory,
  setProjectCover,
  submitVisual,
  type VisualHistory,
  type VisualJob,
  type VisualRequest,
  renameVisualImage,
} from "@/lib/api/visuals";
import { useCaptionStore } from "../captions/store";
import { monitorVideo, visualReference } from "../monitor-video";
import { usePreviewJob } from "../use-editing";
import { useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";

export function visualPolling(value?: VisualHistory): number | false {
  return value?.items.some(
    (j) => j.status === "queued" || j.status === "running",
  )
    ? 2000
    : false;
}

export const visualHistoryKey = (project: string) =>
  ["projects", project, "visual-assets"] as const;

function visualDisplayName(job: VisualJob): string {
  if (job.name?.trim()) return job.name.trim();

  const type =
    job.preset === "thumbnail"
      ? "Thumbnail"
      : job.preset === "cover"
        ? "Cover image"
        : "Poster";

  const mode = job.operation === "edit" ? "Edited" : "Generated";

  return `${type} · ${mode}`;
}

function RenameImage({
  project,
  job,
  onSaved,
}: {
  project: string;
  job: VisualJob;
  onSaved: () => void;
}) {
  const [name, setName] = useState(job.name ?? "");

  useEffect(() => {
    setName(job.name ?? "");
  }, [job.id, job.name]);

  const rename = useMutation({
    mutationFn: () => renameVisualImage(project, job.id, name.trim()),
    retry: false,
    onSuccess: onSaved,
  });

  const cleanName = name.trim();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();

        if (
          cleanName &&
          cleanName !== job.name &&
          !rename.isPending
        ) {
          rename.mutate();
        }
      }}
    >
      <label htmlFor={`visual-name-${job.id}`}>
        Image name
      </label>

      <input
        id={`visual-name-${job.id}`}
        type="text"
        value={name}
        maxLength={80}
        onChange={(e) => setName(e.target.value)}
        required
      />

      <button
        type="submit"
        className="button button-secondary"
        disabled={
          rename.isPending ||
          !cleanName ||
          cleanName === job.name
        }
      >
        {rename.isPending ? "Saving..." : "Save name"}
      </button>

      {rename.isError && (
        <p role="alert">
          Couldn't save image name. Please try again.
        </p>
      )}
    </form>
  );
}
export function VisualImage({
  project,
  job,
  artifact,
  alt,
}: {
  project: string;
  job: string;
  artifact: string;
  alt: string;
}) {
  const key = `${project}:${job}:${artifact}`;
  const [result, setResult] = useState<{
    key: string;
    url?: string;
    error?: boolean;
  }>({ key: "" });

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    let url: string | undefined;
    void downloadAIArtifact(project, job, artifact, abort.signal)
      .then((blob) => {
        if (abort.signal.aborted) return;
        if (blob.type !== "image/png" || blob.size > 16 * 1024 * 1024)
          throw new Error("Invalid image");
        url = URL.createObjectURL(blob);
        setResult({ key, url });
      })
      .catch(() => {
        if (!abort.signal.aborted) setResult({ key, error: true });
      });
    return () => {
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [project, job, artifact, key, attempt]);

  if (result.key !== key || (!result.url && !result.error))
    return <p role="status">Loading verified image…</p>;

  if (result.error)
    return (
      <p role="alert">
        Image unavailable.{" "}
        <button
          type="button"
          className="button button-secondary"
          onClick={() => setAttempt((a) => a + 1)}
        >
          Retry image
        </button>
      </p>
    );

  return (
    <div className="studio-visualImage">
      <div className="studio-visualFrame">
        <Image
          src={result.url ?? ""}
          alt={alt}
          fill
          unoptimized
          sizes="(max-width: 600px) 90vw, 340px"
        />
      </div>
      <a
        href={result.url}
        download={`intentcut-${artifact}.png`}
        className="button button-secondary"
      >
        Download image
      </a>
    </div>
  );
}
function VisualStatus({ project, job }: { project: string; job: VisualJob }) {
  const observed = useAIJobStatus(project, job.id);
  const status = observed.data?.status ?? job.status;
  const stage = observed.data?.progress?.stage;

  let copy =
    status === "queued"
      ? "Waiting to start"
      : status === "succeeded"
        ? "Your image is ready"
        : status === "failed"
          ? "We couldn’t create this image. We didn’t try again, so you won’t be charged twice."
          : stage === "validating_image"
            ? "Checking your image"
            : stage === "publishing_artifacts"
              ? "Saving your image"
              : stage === "preparing_media"
                ? "Checking your starting image"
                : "Creating your image…";
  if (
    status === "failed" &&
    (observed.data?.error_code ?? job.error_code) === "image_outcome_unknown"
  )
    copy =
      "We’re not sure whether this image finished. We didn’t start again, so you won’t be charged twice.";
  return (
    <p role="status">
      {copy}
      {observed.isError && (
        <>
          {" "}
          We couldn’t check progress.{" "}
          <button type="button" onClick={() => void observed.refetch()}>
            Check again
          </button>
        </>
      )}
    </p>
  );
}
export function VisualPromptForm({
  prompt,
  setPrompt,
  preset,
  setPreset,
  operation,
  setOperation,
  source,
  setSource,
  frame,
  setFrame,
  video,
  images,
  pending,
  onSubmit,
  name,
  setName,
}: {
  prompt: string;
  setPrompt: (v: string) => void;
  name?: string;
  setName?: (v: string) => void;
  preset: VisualJob["preset"];
  setPreset: (v: VisualJob["preset"]) => void;
  operation: VisualJob["operation"];
  setOperation: (v: VisualJob["operation"]) => void;
  source: string;
  setSource: (v: string) => void;
  frame: string;
  setFrame: (v: string) => void;
  video?: string;
  images: VisualJob[];
  pending: boolean;
  onSubmit: () => void;
}) {
  return (
    <form
      className="studio-visualForm"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor="visual-prompt">
        Describe your image
        <textarea
          id="visual-prompt"
          value={prompt}
          maxLength={2000}
          rows={4}
          onChange={(e) => setPrompt(e.target.value)}
          required
        />
      </label>
      <label htmlFor="visual-name">
        Image name (optional)
        <input
          id="visual-name"
          type="text"
          value={name ?? ""}
          onChange={(e) => setName?.(e.target.value)}
          maxLength={80}
          placeholder="e.g. Cinematic Travel Thumbnail"
        />
      </label>

      <p className="studio-storyboardNote">
        Give this image a name to find it easily in your library. This won't
        affect the AI-generated image.
      </p>
      
      <label htmlFor="visual-preset">
        What is it for?
        <select
          id="visual-preset"
          value={preset}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "thumbnail" || v === "cover" || v === "poster")
              setPreset(v);
          }}
        >
          <option value="thumbnail">Thumbnail · wide</option>
          <option value="cover">Cover image · wide</option>
          <option value="poster">Poster · tall</option>
        </select>
      </label>
      <p className="studio-storyboardNote">
        These shapes are a guide — the exact image size may vary. You’ll get a
        still image, not a video title card.
      </p>
      <label htmlFor="visual-operation">
        How to create it
        <select
          id="visual-operation"
          value={operation}
          onChange={(e) =>
            setOperation(e.target.value === "edit" ? "edit" : "generate")
          }
        >
          <option value="generate">From my description</option>
          <option value="edit">From an image or video frame</option>
        </select>
      </label>
      {operation === "edit" && (
        <>
          <label htmlFor="visual-source">
            Starting image
            <select
              id="visual-source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              required
            >
              <option value="">Choose a starting image</option>
              {video && (
                <option value={video}>A frame from my current video</option>
              )}
              {images
                .filter((i) => i.artifact_id)
                .map((i) => (
                  <option key={i.id} value={i.artifact_id ?? ""}>
                    {visualDisplayName(i)}
                  </option>
                ))}
            </select>
          </label>
          {source === video && (
            <label htmlFor="visual-frame">
              Which second of the video?
              <input
                id="visual-frame"
                type="number"
                min="0"
                max="600"
                step="0.001"
                value={frame}
                onChange={(e) => setFrame(e.target.value)}
                required
              />
            </label>
          )}
        </>
      )}
      <p>
        Creating an image may use paid credits. We’ll only start when you ask.
      </p>
      <button
        type="submit"
        className="button button-primary"
        disabled={
          pending || !prompt.trim() || (operation === "edit" && !source)
        }
      >
        {pending
          ? "Creating…"
          : operation === "edit"
            ? "Create edited image"
            : "Create image"}
      </button>
    </form>
  );
}
function ConnectedVisuals({ project }: { project: string }) {
  const { scope } = useEditingScope(project);
  const client = useQueryClient();
  const { jobId: baseJob } = usePreviewJob(project);
  const override = useCaptionStore((state) => state.previews[scope]);
  const jobId = override?.jobId ?? baseJob;
  const artifacts = useAIArtifacts(project, jobId);
  const video = monitorVideo(
    artifacts.data?.items ?? [],
    override?.artifactId,
  )?.id;
  const history = useQuery({
    queryKey: visualHistoryKey(project),
    queryFn: ({ signal }) => getVisualHistory(project, signal),
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (q) =>
      q.state.error ? false : visualPolling(q.state.data),
  });
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<VisualJob["preset"]>("thumbnail");
  const [operation, setOperation] =
    useState<VisualJob["operation"]>("generate");
  const [source, setSource] = useState("");
  const [frame, setFrame] = useState("0");
  const selectedSource = visualReference(source, video);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const refresh = () =>
    void client.invalidateQueries({ queryKey: visualHistoryKey(project) });

  const submission = useMutation({
    mutationFn: () => {
    const body: VisualRequest = {
        request_id: requestId,
        prompt,
        preset,
        operation,
        ...(name.trim() ? { name: name.trim() } : {}),
      };
      if (operation === "edit") {
        body.source_artifact_id = selectedSource;
        if (selectedSource === video) body.frame_seconds = Number(frame);
      }
      return submitVisual(project, body);
    },
    retry: false,
    onSuccess: () => {
      setRequestId(crypto.randomUUID());
      setName("");
      refresh();
    },
  });
  const selection = useMutation({
    mutationFn: (id: string) =>
      setProjectCover(project, id, history.data?.cover?.revision ?? 0),
    retry: false,
    onSuccess: refresh,
  });
  if (history.isPending) return <p role="status">Loading your images…</p>;
  if (history.isError)
    return (
      <div role="alert">
        <p>
          Images aren’t available right now. Your project is saved — try again
          in a moment.
        </p>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => void history.refetch()}
        >
          Try again
        </button>
      </div>
    );
  const data = history.data;
  return (
    <div className="studio-visualBody">
      {data.cover && (
        <article>
          <h3>Your project cover</h3>
          <VisualImage
            key={data.cover.artifact_id}
            project={project}
            job={data.cover.job_id}
            artifact={data.cover.artifact_id}
            alt="Your project cover"
          />
        </article>
      )}
      <VisualPromptForm
        prompt={prompt}
        setPrompt={setPrompt}
        preset={preset}
        name={name}
        setName={setName}
        setPreset={setPreset}
        operation={operation}
        setOperation={setOperation}
        source={selectedSource}
        setSource={(value) =>
          setSource(value === video ? "current-video" : value)
        }
        frame={frame}
        setFrame={setFrame}
        video={video}
        images={data.items}
        pending={
          submission.isPending ||
          data.items.some(
            (j) => j.status === "queued" || j.status === "running",
          )
        }
        onSubmit={() => submission.mutate()}
      />
      {submission.isError && (
        <p role="alert">
          {errorText(submission.error)}{" "}
          <button type="button" onClick={() => void history.refetch()}>
            See what’s already done
          </button>
        </p>
      )}
      {selection.isError && (
        <p role="alert">
          {errorText(selection.error)}{" "}
          <button type="button" onClick={() => void history.refetch()}>
            Check your cover
          </button>
        </p>
      )}
      <h3>Your images</h3>
      {!data.items.length && (
        <p>No images yet. Describe one above to create your first.</p>
      )}
      {data.items.map((job) => (
        <article key={job.id} className="studio-visualAsset">
          <h4>{visualDisplayName(job)}</h4>
          {job.status === "succeeded" && (
              <RenameImage
                project={project}
                job={job}
                onSaved={refresh}
              />
            )}
          <p>
            {job.source_artifact_id
              ? "Started from one of your images"
              : "Created from your description"}
            {job.frame_seconds !== null
              ? ` · from ${job.frame_seconds}s in your video`
              : ""}
          </p>
          <VisualStatus project={project} job={job} />
          {job.status === "succeeded" && job.artifact_id && (
            <>
              <VisualImage
                project={project}
                job={job.id}
                artifact={job.artifact_id}
                alt={`Your ${job.preset} image`}
              />
              <button
                type="button"
                className="button button-primary"
                disabled={
                  selection.isPending ||
                  data.cover?.artifact_id === job.artifact_id
                }
                onClick={() => selection.mutate(job.artifact_id ?? "")}
              >
                {data.cover?.artifact_id === job.artifact_id
                  ? "This is your cover"
                  : "Use as cover"}
              </button>
            </>
          )}
        </article>
      ))}
    </div>
  );
}
export function VisualsPanel({ projectId }: { projectId?: string }) {
  return (
    <section className="studio-visuals">
      <header className="studio-panelHeader">
        <h2>AI Visuals</h2>
        <span>Cover &amp; images</span>
      </header>
      {projectId ? (
        <ConnectedVisuals key={projectId} project={projectId} />
      ) : (
        <p>Open a project to create images.</p>
      )}
    </section>
  );
}
