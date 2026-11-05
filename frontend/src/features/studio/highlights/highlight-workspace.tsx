"use client";

import { useEffect, useState } from "react";
import { highlightPreviewUrl } from "@/lib/api/highlights";
import { useEditingScope } from "../workflow";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";
import { useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { usePublicStoryboard } from "../ai-director/hooks/use-public-storyboard";
import { useActiveJobId } from "../store/use-editor-store";
import { draftSyncState, useDraftStore, type TimelineDraft } from "../store/use-draft-store";
import { formatTimestamp, markerPercent } from "./highlight-format";
import "./highlights.css";

function MomentPreview({ url }: { url: string }) {
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<{
    src?: string;
    error?: string;
  }>({});
  const [ready, setReady] = useState(false);
  const [loadedUrl, setLoadedUrl] = useState(url);
  if (loadedUrl !== url) {
    // Defensive: a new clip without a remount starts from a clean state.
    setLoadedUrl(url);
    setPreview({});
    setReady(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;

    // State starts empty on mount (the parent keys each moment) and is reset
    // by the Retry handler, so the effect only performs the fetch.
    void fetch(url, {
      signal: controller.signal,
      credentials: "omit",
      redirect: "error",
      cache: "default",
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            `Source preview failed (HTTP ${response.status}).`
          );
        }

        const blob = await response.blob();

        if (!blob.type.startsWith("video/")) {
          throw new Error(
            "Preview endpoint did not return video."
          );
        }

        if (controller.signal.aborted) return;

        objectUrl = URL.createObjectURL(blob);
        setPreview({ src: objectUrl });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setPreview({
            error:
              error instanceof Error
                ? error.message
                : "Could not load this moment.",
          });
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, attempt]);

  return (
    <div className="highlight-previewFrame">
      {preview.src && (
        <video
          className={`highlight-preview${ready ? " is-ready" : ""}`}
          controls
          playsInline
          preload="auto"
          src={preview.src}
          aria-label="Preview this moment from the original footage"
          onLoadedMetadata={() => setReady(true)}
          onLoadedData={() => setReady(true)}
          onError={() => {
            setReady(false);
            setPreview({
              error: "Your browser could not decode this preview.",
            });
          }}
        />
      )}

      {!ready && (
        <div
          className="highlight-previewPlaceholder"
          role={preview.error ? "alert" : "status"}
        >
          <span className="highlight-previewPlaceholderIcon">
            ▶
          </span>

          <strong>
            {preview.error
              ? "Preview unavailable"
              : "Preparing source clip…"}
          </strong>

          <span>
            {preview.error ??
              "Extracting this moment from the original footage. The first request can take a while."}
          </span>

          {preview.error && (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setPreview({});
                setReady(false);
                setAttempt((value) => value + 1);
              }}
            >
              Retry preview
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Highlights uses the existing draft engine, but replaces the horizontal Timeline UI. */
export function HighlightWorkspace({ projectId, draft }: { projectId: string; draft?: TimelineDraft }) {
  const { scope } = useEditingScope(projectId);
  const activeJobId = useActiveJobId(projectId);
  // Show the source of the currently edited draft, not an unrelated newer job.
  const jobId = draft?.base.jobId ?? activeJobId ?? "";
  const status = useAIJobStatus(projectId, jobId);
  const artifacts = useAIArtifacts(projectId, !draft && status.data?.status === "succeeded" ? jobId : "");
  const artifactId = draft?.base.artifactId ?? artifacts.data?.items.find(item => item.kind === "storyboard")?.id ?? "";
  const storyboard = usePublicStoryboard(projectId, jobId, artifactId, Boolean(jobId && artifactId));
  const receive = useDraftStore(state => state.receive);
  const saved = useDraftStore(state => state.savedByProject[scope]);
  const { move, remove } = useDraftStore();
  const [inspectedId, setInspectedId] = useState<string | null>(null);

  // Recover an editable local draft from an existing successful job without
  // generating anything or writing to the database. Save remains explicit.
  useEffect(() => {
    if (!draft && jobId && artifactId && status.data?.status === "succeeded" && storyboard.data) {
      receive(scope, { jobId, artifactId }, storyboard.data);
    }
  }, [scope, draft, jobId, artifactId, status.data?.status, storyboard.data, receive]);

  const report = storyboard.data?.highlight_discovery;
  const candidates = report?.candidates ?? [];
  const inspected = candidates.find(candidate => candidate.id === inspectedId) ?? candidates[0];
  const originalCut = inspected && storyboard.data
    ? storyboard.data.cuts.find(cut => cut.media_id === inspected.media_id &&
        Math.abs(cut.start_seconds - inspected.start_seconds) < 1e-6 &&
        Math.abs(cut.end_seconds - inspected.end_seconds) < 1e-6)
    : null;
  const currentCut = originalCut && draft?.cuts.find(cut => cut.window_index === originalCut.window_index);
  const sequenceIndex = currentCut && draft ? draft.cuts.findIndex(cut => cut.id === currentCut.id) : -1;
  const total = draft?.cuts.reduce((sum, cut) => sum + cut.end_seconds - cut.start_seconds, 0) ?? 0;
  const reason = currentCut?.editorial_reason ?? originalCut?.editorial_reason;

  if (!jobId) return <p className="highlight-workspaceEmpty" role="status">Create AI Highlights to explore the moments discovered across your video.</p>;
  if (status.data?.status === "queued" || status.data?.status === "running") return <p className="highlight-workspaceEmpty" role="status">AI is finding and assembling highlights. The Navigator will appear when the job finishes.</p>;
  if (status.data?.status === "failed" && !draft) return <p className="highlight-workspaceEmpty" role="alert">This Highlights job failed. Review its status in AI Highlights; your other saved edits are unchanged.</p>;
  if (artifacts.isError && !draft) return <div className="highlight-workspaceEmpty" role="alert">Couldn’t load the Highlights files. <button className="button button-secondary" type="button" onClick={() => void artifacts.refetch()}>Try again</button></div>;
  if (storyboard.isError) return <div className="highlight-workspaceEmpty" role="alert">Couldn’t load the Highlights discovery report. <button className="button button-secondary" type="button" onClick={() => void storyboard.refetch()}>Try again</button></div>;
  if (!report) return <p className="highlight-workspaceEmpty" role="status">{storyboard.isPending ? "Loading AI-discovered moments…" : "This video has no Highlight discovery report. Your video and artifacts are still available."}</p>;

  return <div className="highlight-workspace" role="region" aria-label="AI Highlight Navigator">
    <div className="highlight-workspaceHeading">
      <div>
        <h3>AI Moment Navigator</h3>
        <p className="highlight-note">Explore all {candidates.length} candidates and refine {draft?.cuts.length ?? 0} moments in your edit. The source footage is unchanged.</p>
      </div>
      {draft && <p className="highlight-workspaceSaved" role="status">{draft.cuts.length} moments · {total.toFixed(1)}s · {({ saved: `Version ${saved?.revision} saved`, original: "No edits yet", unsaved: "Unsaved changes", none: "" })[draftSyncState(draft, saved)]}</p>}
    </div>
    <details className="highlight-samplingDetails">
      <summary>How AI searched your footage</summary>
      <p>AI inspected {report.coarse_samples} coarse frames and {report.fine_samples} refinement frames. There can be up to {formatTimestamp(report.max_coarse_gap_seconds)} between coarse samples, so very brief events may be missed.</p>
    </details>
    <div className="highlight-timeline" role="group" aria-label="Highlights across original footage">
      <div className="highlight-track">{candidates.map((candidate, index) => <button key={candidate.id} type="button"
        className={`highlight-marker${candidate.id === inspected?.id ? " is-active" : ""}${draft?.cuts.some(cut => cut.media_id === candidate.media_id && Math.abs(cut.start_seconds - candidate.start_seconds) < 1e-6) ? " is-ai" : " is-excluded"}`}
        style={markerPercent(candidate.start_seconds, candidate.end_seconds, report.source_duration_seconds)}
        aria-pressed={candidate.id === inspected?.id} aria-label={`Inspect moment ${index + 1} at ${formatTimestamp(candidate.start_seconds)}`}
        onClick={() => setInspectedId(candidate.id)} />)}</div>
      <div className="highlight-scale technical"><span>0:00</span><span>{formatTimestamp(report.source_duration_seconds)}</span></div>
    </div>
    <div className="highlight-workspaceGrid">
      <div className="highlight-workspaceDetails">
        {inspected && <>
          <h4>Moment details</h4>
          {/* Preview and its controls are grouped so the edit actions sit next
              to (or directly under) the clip instead of below long copy. */}
          <div className="highlight-momentLayout">
            <MomentPreview key={`${jobId}:${inspected.id}`} url={highlightPreviewUrl(projectId, inspected.media_id, inspected.start_seconds, inspected.end_seconds)} />
            <div className="highlight-momentInfo">
              <p className="highlight-note">Original footage: {formatTimestamp(inspected.start_seconds)}–{formatTimestamp(inspected.end_seconds)} · Relevance {Math.round(inspected.score * 100)}/100</p>
              <p className="highlight-note">{sequenceIndex >= 0 ? `Included as moment ${sequenceIndex + 1} of ${draft?.cuts.length} in your edit.` : originalCut ? "Originally selected by AI, but not in your current edit." : "Considered during discovery, but not included in the generated edit."}</p>
              {currentCut && draft && <div className="studio-draftActions" role="group" aria-label="Edit selected highlight moment">
                <button type="button" className="button button-secondary" disabled={sequenceIndex === 0} onClick={() => move(scope, currentCut.id, -1)}>Move earlier</button>
                <button type="button" className="button button-secondary" disabled={sequenceIndex === draft.cuts.length - 1} onClick={() => move(scope, currentCut.id, 1)}>Move later</button>
                <button type="button" className="button button-secondary" onClick={() => remove(scope, currentCut.id)}>Remove moment</button>
              </div>}
              <h4>{originalCut ? "Why AI selected this moment" : "Why AI considered this moment"}</h4>
              {reason ? <p>{reason}</p> : <p>This moment matched your creative prompt ({Math.round(inspected.score * 100)}/100 relevance). No scene-specific explanation was saved. Watch the source clip to decide whether it fits your story.</p>}
              {!originalCut && <p className="highlight-note">Adding an unselected candidate needs a new validated edit plan; this Navigator does not silently add clips that the saved storyboard cannot render.</p>}
            </div>
          </div>
        </>}
      </div>
      <div className="highlight-workspaceCandidates">
        <h4>Discovered moments</h4>
        <ol className="highlight-list">{candidates.map((candidate, index) => {
          const chosen = draft?.cuts.some(cut => cut.media_id === candidate.media_id && Math.abs(cut.start_seconds - candidate.start_seconds) < 1e-6 && Math.abs(cut.end_seconds - candidate.end_seconds) < 1e-6);
          return <li key={candidate.id}><button type="button" className="highlight-listButton" aria-pressed={candidate.id === inspected?.id} onClick={() => setInspectedId(candidate.id)}>
            <strong>Moment {index + 1} {chosen ? "· In edit" : "· Candidate"}</strong>
            <span>{formatTimestamp(candidate.start_seconds)}–{formatTimestamp(candidate.end_seconds)}</span>
            <span>Prompt relevance: {Math.round(candidate.score * 100)}/100</span>
          </button></li>;
        })}</ol>
      </div>
    </div>
  </div>;
}
