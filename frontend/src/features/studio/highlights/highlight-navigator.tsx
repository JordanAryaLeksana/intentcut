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
import { aiArtifactsKey, useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { usePublicStoryboard } from "../ai-director/hooks/use-public-storyboard";
import { useActiveJobId, useEditorStore } from "../store/use-editor-store";
import { writeSavedJobId } from "../store/job-recovery";
import { formatTimestamp, markerPercent, matchStoryboardCut } from "./highlight-format";
import "./highlights.css";

const AUTO_INTENT =
  "Select the most engaging moments across the full source timeline.";

// Stable fallback while discovery has no data yet: a fresh `[]` literal on
// every render would defeat the candidate-sync guard below and re-trigger
// it endlessly ("Too many re-renders", React #301).
const EMPTY_CANDIDATES: HighlightCandidate[] = [];

function statusMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return "Highlight processing is unavailable in this environment.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return "This source exceeds highlight processing limits.";
  }
  return error instanceof Error ? error.message : "Request was not confirmed.";
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
  const source = sources.find((item) => item.id === mediaId) ?? sources[0] ?? null;
  const effectiveMediaId = source?.id ?? null;

  const candidatesQuery = useQuery({
    queryKey: ["projects", projectId, "highlight-candidates", effectiveMediaId] as const,
    queryFn: ({ signal }) =>
      listHighlightCandidates(projectId as string, effectiveMediaId as string, {}, signal),
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
      current && candidates.some((c) => c.id === current) ? current : (candidates[0]?.id ?? null),
    );
    setIncluded((current) =>
      current === null
        ? candidates.map((c) => c.id)
        : current.filter((id) => candidates.some((c) => c.id === id)),
    );
  }

  const inspected = candidates.find((c) => c.id === inspectedId) ?? null;
  const includedIds = included ?? [];

  const generate = useMutation({
    mutationFn: async () => {
      if (!projectId || !effectiveMediaId) throw new Error("Select a source first.");
      const brief = mode === "guided" ? intent.trim() : AUTO_INTENT;
      if (!brief) throw new Error("Describe the editorial goal.");
      const subset =
        includedIds.length > 0 && includedIds.length < candidates.length ? [...includedIds].sort() : undefined;
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
        void queryClient.invalidateQueries({ queryKey: ["projects", projectId, "ai-jobs", accepted.id] });
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
    () => artifacts.data?.items.find((item) => item.kind === "storyboard") ?? null,
    [artifacts.data],
  );
  const storyboard = usePublicStoryboard(
    projectId ?? "",
    activeJobId ?? "",
    storyboardArtifact?.id ?? "",
    Boolean(projectId && activeJobId && storyboardArtifact),
  );
  const aiMatch = inspected && storyboard.data ? matchStoryboardCut(inspected, storyboard.data.cuts) : null;

  if (!projectId) {
    return <p>Open a project to discover highlight candidates.</p>;
  }

  const generating = generate.isPending || jobStatus.data?.status === "queued" || jobStatus.data?.status === "running";

  return (
    <div className="highlight-navigator">
      <header className="studio-panelHeader">
        <h2>AI Highlight Navigator</h2>
        <span>Long-form</span>
      </header>

      <section aria-label="Long-form source" className="highlight-section">
        <label className="highlight-label" htmlFor="highlight-source">
          Source
        </label>
        {media.isPending ? (
          <p role="status">Loading saved footage…</p>
        ) : media.isError ? (
          <div>
            <p role="alert">Could not load saved footage.</p>
            <button type="button" className="button button-secondary" onClick={() => void media.refetch()}>
              Retry footage
            </button>
          </div>
        ) : !sources.length ? (
          <p>Upload a video in the Media Pool to begin highlight discovery.</p>
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
                  {item.original_filename} · {formatTimestamp(item.duration_seconds)}
                </option>
              ))}
            </select>
            {source && (
              <p className="highlight-sourceMeta technical" role="status">
                {formatTimestamp(0)} – {formatTimestamp(source.duration_seconds)} · {source.duration_seconds.toFixed(1)}s
              </p>
            )}
          </>
        )}
      </section>

      {effectiveMediaId && (
        <section aria-label="Discovered candidates" className="highlight-section">
          <h3 className="highlight-heading">Candidates</h3>
          {candidatesQuery.isPending ? (
            <p role="status">Scanning the full source timeline…</p>
          ) : candidatesQuery.isError ? (
            <div>
              <p role="alert">{statusMessage(candidatesQuery.error)}</p>
              <button type="button" className="button button-secondary" onClick={() => void candidatesQuery.refetch()}>
                Retry discovery
              </button>
            </div>
          ) : !candidates.length ? (
            <p>No candidate moments survived deduplication for this source.</p>
          ) : (
            <>
              <div
                className="highlight-timeline"
                role="group"
                aria-label={`Candidate markers across ${formatTimestamp(candidatesQuery.data?.duration_seconds ?? 0)}`}
              >
                <div className="highlight-track">
                  {candidates.map((candidate) => {
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
                        aria-label={`${candidate.id} ${formatTimestamp(candidate.start_seconds)} to ${formatTimestamp(candidate.end_seconds)}, heuristic score ${candidate.score.toFixed(2)}${excluded ? ", excluded from generation" : ""}`}
                        title={`${candidate.id} · ${formatTimestamp(candidate.start_seconds)}–${formatTimestamp(candidate.end_seconds)}`}
                        onClick={() => setInspectedId(candidate.id)}
                      />
                    );
                  })}
                </div>
                <div className="highlight-scale technical" aria-hidden="true">
                  <span>{formatTimestamp(0)}</span>
                  <span>{formatTimestamp(candidatesQuery.data?.duration_seconds ?? 0)}</span>
                </div>
              </div>

              <ol className="highlight-list">
                {candidates.map((candidate) => (
                  <li key={candidate.id} className={candidate.id === inspectedId ? "is-active" : ""}>
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
                        aria-label={`Include ${candidate.id} in generation`}
                      />
                      <button
                        type="button"
                        className="highlight-listButton"
                        onClick={() => setInspectedId(candidate.id)}
                        aria-current={candidate.id === inspectedId}
                      >
                        <strong>{candidate.id}</strong>
                        <span className="technical">
                          {formatTimestamp(candidate.start_seconds)}–{formatTimestamp(candidate.end_seconds)}
                        </span>
                        <span>Heuristic {candidate.score.toFixed(2)}</span>
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
        <section aria-label="Candidate inspector" className="highlight-section">
          <h3 className="highlight-heading">Inspector · {inspected.id}</h3>
          <video
            key={inspected.id}
            className="highlight-preview"
            controls
            preload="metadata"
            playsInline
            src={highlightPreviewUrl(projectId, inspected.media_id, inspected.start_seconds, inspected.end_seconds)}
            aria-label={`Preview of candidate ${inspected.id}`}
          />
          <dl className="highlight-facts">
            <div>
              <dt>Source range</dt>
              <dd className="technical">
                {formatTimestamp(inspected.start_seconds)} – {formatTimestamp(inspected.end_seconds)} (
                {(inspected.end_seconds - inspected.start_seconds).toFixed(1)}s)
              </dd>
            </div>
            <div>
              <dt>Heuristic score</dt>
              <dd className="technical">
                {inspected.score.toFixed(3)} · exposure {inspected.components.exposure?.toFixed(2) ?? "–"} · color{" "}
                {inspected.components.color?.toFixed(2) ?? "–"} · sharpness{" "}
                {inspected.components.sharpness?.toFixed(2) ?? "–"}
              </dd>
            </div>
            <div>
              <dt>Evidence</dt>
              <dd>Local pixel heuristics only — not semantic understanding.</dd>
            </div>
            {aiMatch?.editorial_reason && (
              <div>
                <dt>Muse editorial reason</dt>
                <dd>
                  {aiMatch.editorial_reason}
                  {aiMatch.playback_order !== undefined && (
                    <span className="technical"> · playback #{aiMatch.playback_order + 1}</span>
                  )}
                </dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {effectiveMediaId && candidates.length > 0 && (
        <section aria-label="Editorial workflow" className="highlight-section">
          <h3 className="highlight-heading">Generate highlights</h3>
          <fieldset className="highlight-mode">
            <legend>Editorial mode</legend>
            <label>
              <input type="radio" name="highlight-mode" checked={mode === "auto"} onChange={() => setMode("auto")} />
              Auto — AI determines the moments
            </label>
            <label>
              <input type="radio" name="highlight-mode" checked={mode === "guided"} onChange={() => setMode("guided")} />
              Guided — my intent guides selection
            </label>
          </fieldset>
          {mode === "guided" && (
            <>
              <label className="highlight-label" htmlFor="highlight-intent">
                Editorial intent
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
            Target duration (seconds, max 120)
          </label>
          <input
            id="highlight-target"
            type="number"
            min={1}
            max={120}
            step={1}
            value={targetSeconds}
            onChange={(event) => setTargetSeconds(Math.min(120, Math.max(1, Number(event.target.value) || 1)))}
          />
          <p className="highlight-note">
            {includedIds.length} of {candidates.length} candidates included. Manual selection applies only when you
            generate; it never changes an existing AI result.
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={generating || includedIds.length === 0 || (mode === "guided" && !intent.trim())}
            onClick={() => generate.mutate()}
          >
            {generate.isPending
              ? "Submitting…"
              : jobStatus.data?.status === "queued" || jobStatus.data?.status === "running"
                ? "Generating…"
                : "Generate Highlights"}
          </button>
          {generate.isError && <p role="alert">{statusMessage(generate.error)}</p>}
          {activeJobId && jobStatus.data && (
            <p role="status" className="highlight-note">
              Job {jobStatus.data.status}
              {jobStatus.data.status === "succeeded" &&
                " — storyboard, timeline, revisions, captions, and MP4 download are available in the existing workflow."}
              {jobStatus.data.status === "failed" && ` — ${jobStatus.data.error_code ?? "processing_failed"}.`}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
