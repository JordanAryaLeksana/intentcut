"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import {
  createHighlightJob,
  highlightPreviewUrl,
  listHighlightCandidates,
  type HighlightCandidate,
} from "@/lib/api/highlights";
import { useProjectMedia } from "../media/hooks/use-project-media";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";
import {
  aiArtifactsKey,
  useAIArtifacts,
} from "../ai-director/hooks/use-ai-artifacts";
import { usePublicStoryboard } from "../ai-director/hooks/use-public-storyboard";
import { useActiveJobId, useEditorStore } from "../store/use-editor-store";
import { writeSavedJobId } from "../store/job-recovery";
import {
  formatTimestamp,
  markerPercent,
  matchStoryboardCut,
} from "./highlight-format";
import "./highlights.css";

const AUTO_INTENT =
  "Select the most engaging moments across the full source timeline.";

// Stable fallback while discovery has no data yet: a fresh `[]` literal on
// every render would defeat the candidate-sync guard below and re-trigger
// it endlessly ("Too many re-renders", React #301).
const EMPTY_CANDIDATES: HighlightCandidate[] = [];

function statusMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return "Finding highlights isn’t available right now. Your footage is unchanged — try again later.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return "This video is too long for highlight search. Try a shorter video.";
  }
  return error instanceof Error
    ? error.message
    : "We couldn’t confirm that. Check again before trying once more.";
}

function momentLabel(candidates: HighlightCandidate[], id: string): string {
  const index = candidates.findIndex((c) => c.id === id);
  return index >= 0 ? `Moment ${index + 1}` : "This moment";
}

export function HighlightNavigator({ projectId }: { projectId?: string }) {
  const media = useProjectMedia(projectId ?? "");
  const [mediaId, setMediaId] = useState<string | null>(null);
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const [included, setIncluded] = useState<string[] | null>(null);
  const [prevProject, setPrevProject] = useState(projectId);
  if (prevProject !== projectId) {
    setPrevProject(projectId);
    setMediaId(null);
    setInspectedId(null);
    setIncluded(null);
  }
  const [mode, setMode] = useState<"auto" | "guided">("auto");
  const [intent, setIntent] = useState("");
  const [targetSeconds, setTargetSeconds] = useState(30);
  const queryClient = useQueryClient();
  const setActiveJob = useEditorStore((state) => state.setActiveJob);
  const activeJobId = useActiveJobId(projectId ?? "");

  const sources = useMemo(
    () => (media.data ?? []).filter((item) => item.duration_seconds > 0),
    [media.data],
  );
  const source =
    sources.find((item) => item.id === mediaId) ?? sources[0] ?? null;
  const effectiveMediaId = source?.id ?? null;

  const candidatesQuery = useQuery({
    queryKey: [
      "projects",
      projectId,
      "highlight-candidates",
      effectiveMediaId,
    ] as const,
    queryFn: ({ signal }) =>
      listHighlightCandidates(
        projectId as string,
        effectiveMediaId as string,
        {},
        signal,
      ),
    enabled: Boolean(projectId && effectiveMediaId),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const candidates = candidatesQuery.data?.candidates ?? EMPTY_CANDIDATES;

  const [prevCandidates, setPrevCandidates] = useState(candidates);
  if (prevCandidates !== candidates) {
    setPrevCandidates(candidates);
    setInspectedId((current) =>
      current && candidates.some((c) => c.id === current)
        ? current
        : (candidates[0]?.id ?? null),
    );
    setIncluded((current) =>
      current === null
        ? candidates.map((c) => c.id)
        : current.filter((id) => candidates.some((c) => c.id === id)),
    );
  }

  const inspected = candidates.find((c) => c.id === inspectedId) ?? null;
  const includedIds = included ?? [];
  const previewRequestUrl =
    projectId && inspected
      ? highlightPreviewUrl(
          projectId,
          inspected.media_id,
          inspected.start_seconds,
          inspected.end_seconds,
        )
      : null;

  const [previewState, setPreviewState] = useState<{
    requestUrl: string;
    blobUrl: string | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!previewRequestUrl) {
      return;
    }

    const controller = new AbortController();
    let objectUrl: string | null = null;

    async function loadPreview() {
      try {
        const response = await fetch(previewRequestUrl!, {
          method: "GET",
          mode: "cors",
          credentials: "omit",
          cache: "no-store",
          redirect: "error",
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Preview request failed (${response.status}).`);
        }

        const blob = await response.blob();

        if (controller.signal.aborted) return;

        if (!blob.type.startsWith("video/")) {
          throw new Error("Invalid preview video response.");
        }

        objectUrl = URL.createObjectURL(blob);

        setPreviewState({
          requestUrl: previewRequestUrl!,
          blobUrl: objectUrl,
          error: null,
        });
      } catch (error) {
        if (controller.signal.aborted) return;

        setPreviewState({
          requestUrl: previewRequestUrl!,
          blobUrl: null,
          error:
            error instanceof Error
              ? error.message
              : "Could not load the video preview.",
        });
      }
    }

    void loadPreview();

    return () => {
      controller.abort();

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [previewRequestUrl]);

  const currentPreview =
    previewState?.requestUrl === previewRequestUrl ? previewState : null;
  const generate = useMutation({
    mutationFn: async () => {
      if (!projectId || !effectiveMediaId)
        throw new Error("Select a source first.");
      const brief = mode === "guided" ? intent.trim() : AUTO_INTENT;
      if (!brief) throw new Error("Describe the editorial goal.");
      const subset =
        includedIds.length > 0 && includedIds.length < candidates.length
          ? [...includedIds].sort()
          : undefined;
      return createHighlightJob(projectId, {
        kind: "highlight",
        intent: brief,
        target_seconds: targetSeconds,
        media_ids: [effectiveMediaId],
        ...(subset ? { candidate_ids: subset } : {}),
      });
    },
    onSuccess: (accepted) => {
      if (projectId) {
        setActiveJob(projectId, accepted.id);
        // Same session-recovery contract as AI Director first cuts, so a
        // refresh restores this job in the monitor and timeline.
        writeSavedJobId(projectId, sessionStorage, accepted.id);
        void queryClient.invalidateQueries({
          queryKey: ["projects", projectId, "ai-jobs", accepted.id],
        });
      }
    },
  });

  const jobStatus = useAIJobStatus(projectId ?? "", activeJobId);
  // The artifacts query may have cached an empty list while this job was
  // still running; refresh it on success so the existing Program Monitor
  // and Narrative Timeline (which share that query) populate in-session.
  const jobSucceeded = jobStatus.data?.status === "succeeded";
  useEffect(() => {
    if (jobSucceeded && projectId && activeJobId) {
      void queryClient.invalidateQueries({
        queryKey: aiArtifactsKey(projectId, activeJobId),
      });
    }
  }, [jobSucceeded, projectId, activeJobId, queryClient]);
  const artifacts = useAIArtifacts(projectId ?? "", activeJobId ?? "");
  const storyboardArtifact = useMemo(
    () =>
      artifacts.data?.items.find((item) => item.kind === "storyboard") ?? null,
    [artifacts.data],
  );
  const storyboard = usePublicStoryboard(
    projectId ?? "",
    activeJobId ?? "",
    storyboardArtifact?.id ?? "",
    Boolean(projectId && activeJobId && storyboardArtifact),
  );
  const aiMatch =
    inspected && storyboard.data
      ? matchStoryboardCut(inspected, storyboard.data.cuts)
      : null;

  if (!projectId) {
    return <p>Open a project to find your best moments.</p>;
  }

  const generating =
    generate.isPending ||
    jobStatus.data?.status === "queued" ||
    jobStatus.data?.status === "running";

  return (
    <div className="highlight-navigator">
      <header className="studio-panelHeader">
        <h2>Highlights</h2>
        <span>Best moments</span>
      </header>

      <section aria-label="Your video" className="highlight-section">
        <label className="highlight-label" htmlFor="highlight-source">
          Your video
        </label>
        {media.isPending ? (
          <p role="status">Loading your footage…</p>
        ) : media.isError ? (
          <div>
            <p role="alert">We couldn’t load your footage.</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void media.refetch()}
            >
              Try again
            </button>
          </div>
        ) : !sources.length ? (
          <p>Add a video in Media Library to find your best moments.</p>
        ) : (
          <>
            <select
              id="highlight-source"
              value={effectiveMediaId ?? ""}
              onChange={(event) => {
                setMediaId(event.target.value);
                setInspectedId(null);
                setIncluded(null);
              }}
            >
              {sources.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.original_filename} ·{" "}
                  {formatTimestamp(item.duration_seconds)}
                </option>
              ))}
            </select>
            {source && (
              <p className="highlight-sourceMeta technical" role="status">
                {formatTimestamp(0)} –{" "}
                {formatTimestamp(source.duration_seconds)} ·{" "}
                {source.duration_seconds.toFixed(1)}s
              </p>
            )}
          </>
        )}
      </section>

      {effectiveMediaId && (
        <section aria-label="Your best moments" className="highlight-section">
          <h3 className="highlight-heading">Your best moments</h3>
          {candidatesQuery.isPending ? (
            <p role="status">Looking through your whole video…</p>
          ) : candidatesQuery.isError ? (
            <div>
              <p role="alert">{statusMessage(candidatesQuery.error)}</p>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => void candidatesQuery.refetch()}
              >
                Look again
              </button>
            </div>
          ) : !candidates.length ? (
            <p>
              We didn’t spot standout moments in this video. Try a different
              video, or create a first cut with AI Director instead.
            </p>
          ) : (
            <>
              <div
                className="highlight-timeline"
                role="group"
                aria-label={`Your best moments across ${formatTimestamp(candidatesQuery.data?.duration_seconds ?? 0)}`}
              >
                <div className="highlight-track">
                  {candidates.map((candidate, candidateIndex) => {
                    const { left, width } = markerPercent(
                      candidate.start_seconds,
                      candidate.end_seconds,
                      candidatesQuery.data?.duration_seconds ?? 0,
                    );
                    const active = candidate.id === inspectedId;
                    const excluded = !includedIds.includes(candidate.id);
                    return (
                      <button
                        key={candidate.id}
                        type="button"
                        className={`highlight-marker${active ? " is-active" : ""}${excluded ? " is-excluded" : ""}${aiMatch && candidate.id === inspectedId ? " is-ai" : ""}`}
                        style={{ left, width }}
                        aria-pressed={active}
                        aria-label={`Moment ${candidateIndex + 1}, ${formatTimestamp(candidate.start_seconds)} to ${formatTimestamp(candidate.end_seconds)}, score ${candidate.score.toFixed(2)}${excluded ? ", not included" : ""}`}
                        title={`Moment ${candidateIndex + 1} · ${formatTimestamp(candidate.start_seconds)}–${formatTimestamp(candidate.end_seconds)}`}
                        onClick={() => setInspectedId(candidate.id)}
                      />
                    );
                  })}
                </div>
                <div className="highlight-scale technical" aria-hidden="true">
                  <span>{formatTimestamp(0)}</span>
                  <span>
                    {formatTimestamp(
                      candidatesQuery.data?.duration_seconds ?? 0,
                    )}
                  </span>
                </div>
              </div>

              <ol className="highlight-list">
                {candidates.map((candidate, candidateIndex) => (
                  <li
                    key={candidate.id}
                    className={candidate.id === inspectedId ? "is-active" : ""}
                  >
                    <label className="highlight-listRow">
                      <input
                        type="checkbox"
                        checked={includedIds.includes(candidate.id)}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setIncluded((current) => {
                            const base = current ?? candidates.map((c) => c.id);
                            return checked
                              ? [...base, candidate.id]
                              : base.filter((id) => id !== candidate.id);
                          });
                        }}
                        aria-label={`Include Moment ${candidateIndex + 1} in your highlights`}
                      />
                      <button
                        type="button"
                        className="highlight-listButton"
                        onClick={() => setInspectedId(candidate.id)}
                        aria-current={candidate.id === inspectedId}
                      >
                        <strong>Moment {candidateIndex + 1}</strong>
                        <span className="technical">
                          {formatTimestamp(candidate.start_seconds)}–
                          {formatTimestamp(candidate.end_seconds)}
                        </span>
                        <span>Score {candidate.score.toFixed(2)}</span>
                      </button>
                    </label>
                  </li>
                ))}
              </ol>
            </>
          )}
        </section>
      )}

      {inspected && (
        <section aria-label="About this moment" className="highlight-section">
          <h3 className="highlight-heading">
            {momentLabel(candidates, inspected.id)}
          </h3>
          {!currentPreview ? (
            <p role="status">Loading moment preview…</p>
          ) : currentPreview.error ? (
            <p role="alert">{currentPreview.error}</p>
          ) : currentPreview.blobUrl ? (
            <video
              key={inspected.id}
              className="highlight-preview"
              controls
              preload="metadata"
              playsInline
              src={currentPreview.blobUrl}
              aria-label={`Preview of ${momentLabel(candidates, inspected.id)}`}
            />
          ) : null}
          <dl className="highlight-facts">
            <div>
              <dt>When it happens</dt>
              <dd className="technical">
                {formatTimestamp(inspected.start_seconds)} –{" "}
                {formatTimestamp(inspected.end_seconds)} (
                {(inspected.end_seconds - inspected.start_seconds).toFixed(1)}s)
              </dd>
            </div>
            <div>
              <dt>How strong it looks</dt>
              <dd className="technical">
                Score {inspected.score.toFixed(2)} · brightness{" "}
                {inspected.components.exposure?.toFixed(2) ?? "–"} · colour{" "}
                {inspected.components.color?.toFixed(2) ?? "–"} · sharpness{" "}
                {inspected.components.sharpness?.toFixed(2) ?? "–"}
              </dd>
            </div>
            <div>
              <dt>How we chose it</dt>
              <dd>
                By picture quality — brightness, colour, and sharpness. We
                haven’t judged what’s happening in the scene.
              </dd>
            </div>
            {aiMatch?.editorial_reason && (
              <div>
                <dt>Why your AI Director picked it</dt>
                <dd>
                  {aiMatch.editorial_reason}
                  {aiMatch.playback_order !== undefined && (
                    <span className="technical">
                      {" "}
                      · plays {aiMatch.playback_order + 1} in your story
                    </span>
                  )}
                </dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {effectiveMediaId && candidates.length > 0 && (
        <section
          aria-label="Make your highlights"
          className="highlight-section"
        >
          <h3 className="highlight-heading">Make your highlights</h3>
          <fieldset className="highlight-mode">
            <legend>How should we choose?</legend>
            <label>
              <input
                type="radio"
                name="highlight-mode"
                checked={mode === "auto"}
                onChange={() => setMode("auto")}
              />
              For me — pick the strongest moments
            </label>
            <label>
              <input
                type="radio"
                name="highlight-mode"
                checked={mode === "guided"}
                onChange={() => setMode("guided")}
              />
              With my guidance — I’ll say what matters
            </label>
          </fieldset>
          {mode === "guided" && (
            <>
              <label className="highlight-label" htmlFor="highlight-intent">
                What moments matter most?
              </label>
              <textarea
                id="highlight-intent"
                rows={3}
                maxLength={1000}
                value={intent}
                onChange={(event) => setIntent(event.target.value)}
                placeholder="e.g. the tensest on-stage moments for a recap"
              />
            </>
          )}
          <label className="highlight-label" htmlFor="highlight-target">
            How long should it be? (seconds, up to 120)
          </label>
          <input
            id="highlight-target"
            type="number"
            min={1}
            max={120}
            step={1}
            value={targetSeconds}
            onChange={(event) =>
              setTargetSeconds(
                Math.min(120, Math.max(1, Number(event.target.value) || 1)),
              )
            }
          />
          <p className="highlight-note">
            {includedIds.length} of {candidates.length} moments included.
            Ticking moments only matters when you create highlights — it never
            changes a video you already made.
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={
              generating ||
              includedIds.length === 0 ||
              (mode === "guided" && !intent.trim())
            }
            onClick={() => generate.mutate()}
          >
            {generate.isPending
              ? "Starting…"
              : jobStatus.data?.status === "queued" ||
                  jobStatus.data?.status === "running"
                ? "Creating…"
                : "Create highlights"}
          </button>
          {generate.isError && (
            <p role="alert">{statusMessage(generate.error)}</p>
          )}
          {activeJobId && jobStatus.data && (
            <p role="status" className="highlight-note">
              Your highlights are{" "}
              {jobStatus.data.status === "succeeded"
                ? "ready"
                : jobStatus.data.status === "failed"
                  ? "not ready"
                  : "being created"}
              {jobStatus.data.status === "succeeded" &&
                " — watch them in Preview, refine them in Timeline and Captions, then download your video."}
              {jobStatus.data.status === "failed" &&
                " — something went wrong while creating them. Your footage is unchanged; you can try again."}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
