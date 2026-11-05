import type { AIJobProgress } from "@/lib/api/contracts";
import type { RenderVersion } from "@/lib/api/editing";
import type { RevisionProposal } from "@/lib/api/revisions";
import { failureDescription, STAGE_COPY, type ObservedJob } from "./processing-state";

export interface LifecycleStep {
  key: string;
  title: string;
  state: "complete" | "active" | "waiting" | "failed" | "rejected" | "unknown";
  timestamp?: string | null;
  description?: string;
  progress?: AIJobProgress | null;
}
export interface LifecyclePhase {
  id: string;
  label: string;
  createdAt?: string | null;
  revision: number;
  active: boolean;
  status: string;
  steps: LifecycleStep[];
  instruction?: string;
}

const unique = <T,>(items: T[], id: (item: T) => string) =>
  [...new Map([...items].reverse().map(item => [id(item), item])).values()].reverse();
const timestamp = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;

export function activityRenderLabel(status: string): string {
  switch (status) {
    case "queued": return "Queued — Waiting for worker";
    case "running": return "Rendering video";
    case "succeeded": return "Your video is ready";
    case "failed": return "Failed — Video could not be rendered";
    default: return "Checking video status…";
  }
}

export function renderPhase(version: RenderVersion, job?: ObservedJob): LifecyclePhase {
  const active = version.status === "queued" || version.status === "running";
  // The render list owns completion. A cached job snapshot can lag its invalidation.
  const progress = version.status === "running" && job?.status === "running" ? job.progress : null;
  const steps: LifecycleStep[] = [{ key: "queued", title: "Queued", state: version.status === "queued" ? "waiting" : "complete", timestamp: job?.created_at }];
  if (job?.started_at || version.status === "running" || version.status === "succeeded") {
    steps.push({ key: "rendering", title: "Rendering video", state: version.status === "succeeded" ? "complete" : version.status === "running" ? "active" : "unknown", timestamp: job?.started_at,
      description: progress ? renderStageTitle(progress) : undefined, progress });
  }
  if (!active) steps.push({ key: "result", title: version.status === "succeeded" ? "Your video is ready" : "Render failed", state: version.status === "succeeded" ? "complete" : "failed",
    timestamp: job?.status === version.status ? job.finished_at : null,
    description: version.status === "failed" ? failureDescription(job?.error_code ?? null) : undefined });
  return { id: version.job_id, label: `Version ${version.revision} Render`, createdAt: job?.created_at, revision: version.revision * 2,
    active, status: activityRenderLabel(version.status), steps };
}

function renderStageTitle(progress: AIJobProgress) {
  // The shared First Cut copy calls publishing "Saving your first cut".
  if (progress.stage === "publishing_artifacts") return "Publishing video";
  if (progress.stage === "extracting_windows") return "Extracting selected moments";
  return STAGE_COPY[progress.stage].title;
}

export function revisionPhase(proposal: RevisionProposal, index: number): LifecyclePhase {
  const ready = proposal.after !== null && proposal.job_status === "succeeded";
  const active = proposal.state === "pending" && (proposal.job_status === "queued" || proposal.job_status === "running");
  const steps: LifecycleStep[] = [{ key: "requested", title: "Revision requested", state: "complete", timestamp: proposal.created_at }];
  if (active || ready) steps.push({ key: "processing", title: proposal.job_status === "queued" ? "Queued — Waiting for AI" : "AI processing",
    state: ready ? "complete" : proposal.job_status === "running" ? "active" : "waiting",
    description: active && proposal.progress ? STAGE_COPY[proposal.progress.stage].title : undefined,
    progress: active ? proposal.progress : null });
  if (ready) steps.push({ key: "ready", title: "Proposal ready", state: "complete", timestamp: proposal.finished_at });
  let status = active ? (proposal.job_status === "queued" ? "Queued — Waiting for AI" : "AI processing") : ready ? "Proposal ready" : "Checking proposal status…";
  if (proposal.state === "accepted") {
    status = "Proposal accepted";
    steps.push({ key: "decision", title: status, state: "complete", description: `Saved as version ${proposal.applied_revision}.` });
  } else if (proposal.state === "rejected") {
    status = "Proposal rejected";
    steps.push({ key: "decision", title: status, state: "rejected", description: "Your draft is unchanged." });
  } else if (proposal.state === "stale") {
    status = "Proposal out of date";
    steps.push({ key: "decision", title: status, state: "unknown", description: "Your saved draft changed. Request a new revision." });
  } else if (proposal.state === "failed" || proposal.job_status === "failed") {
    status = "Revision failed";
    steps.push({ key: "result", title: status, state: "failed", timestamp: proposal.finished_at,
      description: proposal.error_code === "unsupported_revision" ? "Only reordering or removing moments is supported. Your draft is unchanged." : "The revision could not be completed. Your draft is unchanged." });
  }
  return { id: proposal.id, label: `Revision ${index + 1}`, createdAt: proposal.created_at, revision: proposal.base_revision * 2 + 1,
    active, status, steps, instruction: proposal.instruction };
}

/** Rebuild from persisted snapshots, never append polling responses as new events. */
export function buildLifecyclePhases(versions: RenderVersion[], proposals: RevisionProposal[], jobs: Map<string, ObservedJob>): LifecyclePhase[] {
  const orderedProposals = unique(proposals, p => p.id).reverse();
  if (orderedProposals.every(p => timestamp(p.created_at) !== null)) {
    orderedProposals.sort((a, b) => timestamp(a.created_at)! - timestamp(b.created_at)! || a.id.localeCompare(b.id));
  }
  const phases = [
    ...orderedProposals.map(revisionPhase),
    ...unique(versions, v => v.job_id).reverse().map(v => renderPhase(v, jobs.get(v.job_id))),
  ];
  const dated = phases.every(p => timestamp(p.createdAt) !== null);
  // While render metadata loads (or for older timestamp-less responses), use
  // persisted draft dependencies and each endpoint's oldest-first order.
  return phases.sort((a, b) => dated
    ? timestamp(a.createdAt)! - timestamp(b.createdAt)! || a.revision - b.revision || a.id.localeCompare(b.id)
    : a.revision - b.revision);
}

export interface ActivitySummary {
  /** "In progress" for active work, otherwise the state of the current video. */
  overline: "In progress" | "Current video" | "Latest update";
  title: string;
  /** Secondary outcome (e.g. a later revision request) that did not change the video. */
  note?: string;
  phaseId?: string;
}

const READY = activityRenderLabel("succeeded");
const outputLabel = (phase: LifecyclePhase) => phase.label.replace(/ Render$/, "");
function revisionOutcomeNote(phase: LifecyclePhase): string {
  switch (phase.status) {
    case "Revision failed": return `${phase.label} didn’t work · Your draft and video are unchanged.`;
    case "Proposal rejected": return `${phase.label} was turned down · Your draft is unchanged.`;
    case "Proposal out of date": return `${phase.label} is out of date · Ask for a new revision.`;
    case "Proposal accepted": return `${phase.label} was accepted · Make a new video to watch it.`;
    case "Proposal ready": return `${phase.label} is ready · Choose whether to use it in Rework your story.`;
    default: return `${phase.label} · ${phase.status}`;
  }
}

/**
 * Separates what the user can watch now from revision/render history, so a
 * finished failure of a *request* never headlines over a ready video.
 */
export function summarizeActivity(
  phases: LifecyclePhase[],
  renderIds: ReadonlySet<string>,
  first: { label: string; ready: boolean },
): ActivitySummary | null {
  const latest = phases.at(-1);
  if (!latest) return null;
  const active = phases.findLast(phase => phase.active);
  if (active) return { overline: "In progress", title: `${active.label} · ${active.status}`, phaseId: active.id };
  const renders = phases.filter(phase => renderIds.has(phase.id));
  const ready = renders.findLast(phase => phase.status === READY);
  const lastRender = renders.at(-1);
  const current = ready
    ? { title: `${ready.label} · ${ready.status}`, phaseId: ready.id }
    : first.ready ? { title: `${first.label} · ${READY}`, phaseId: undefined } : null;
  if (!current) return { overline: "Latest update", title: `${latest.label} · ${latest.status}`, phaseId: latest.id };
  const notes: string[] = [];
  if (lastRender && lastRender !== ready)
    notes.push(`${outputLabel(lastRender)} couldn’t be made · ${ready ? outputLabel(ready) : first.label} is still ready to watch.`);
  if (!renderIds.has(latest.id)) notes.push(revisionOutcomeNote(latest));
  return { overline: "Current video", ...current, ...(notes.length ? { note: notes.join(" ") } : {}) };
}
