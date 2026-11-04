"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import type { ObservedJob } from "./processing-state";
import { elapsedSeconds, failureDescription, formatElapsed, STAGE_COPY } from "./processing-state";

function subscribeClock(notify: () => void) {
  const timer = setInterval(notify, 1_000);
  return () => clearInterval(timer);
}
const clockSnapshot = () => Math.floor(Date.now() / 1_000) * 1_000;
const noClock = () => null;
const idleSubscription = () => () => {};

export function useProcessingClock(active: boolean): number | null {
  return useSyncExternalStore(active ? subscribeClock : idleSubscription, active ? clockSnapshot : noClock, noClock);
}

export function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return <time dateTime={value} title={value}>{new Date(value).toISOString().slice(11, 19)} UTC</time>;
}

export function ProcessingTimeline({ job, now = null, unconfirmed = false, recoveryAction }: {
  job: ObservedJob;
  now?: number | null;
  unconfirmed?: boolean;
  recoveryAction?: ReactNode;
}) {

  return (
    <section className="processing-timeline" aria-label="Creating your video">
      <ProcessingOverview job={job} now={now} unconfirmed={unconfirmed} recoveryAction={recoveryAction} />
      <ol className="processing-milestones" aria-label="How your video is coming along">
        <FirstCutMilestones job={job} unconfirmed={unconfirmed} />
      </ol>
      {job.status === "failed" && job.lastObservedProgress && (
        <p className="processing-lastStage">Last step we saw: {STAGE_COPY[job.lastObservedProgress.stage].title}. That alone doesn’t tell us why it stopped.</p>
      )}
      {job.status === "succeeded" && !unconfirmed && (
        <a className="button button-primary processing-viewCut" href="#monitor-heading">Watch your video</a>
      )}
      <details className="processing-jobId"><summary>Details for support</summary><p className="technical">{job.id}</p></details>
    </section>
  );
}

export function FirstCutMilestones({ job, unconfirmed = false, label }: {
  job: ObservedJob; unconfirmed?: boolean; label?: string;
}) {
  const terminal = job.status === "succeeded" || job.status === "failed";
  const progress = !unconfirmed && job.status === "running" ? job.progress : null;
  const stage = progress ? STAGE_COPY[progress.stage] : null;
  return <>
        <li data-state="complete">
          {label && <p className="processing-phaseLabel">{label}</p>}
          <h4>Request received</h4><Timestamp value={job.created_at} />
        </li>
        <li data-state={unconfirmed ? "unknown" : job.status === "queued" ? "waiting" : progress ? "active" : job.status === "succeeded" ? "complete" : "unknown"} aria-current={progress ? "step" : undefined}>
          <h4>{job.status === "queued" ? "Waiting to start" : "Creating your video"}</h4>
          {job.status === "queued" ? <p>Your video is waiting its turn.</p> : <Timestamp value={job.started_at} />}
          {progress && <p>{stage?.title} · Started <Timestamp value={progress.stage_started_at} /></p>}
        </li>
        {terminal && (
          <li data-state={job.status === "succeeded" ? "complete" : "failed"}>
            <h4>{job.status === "succeeded" ? "Your video is ready" : "This try didn’t finish"}</h4>
            <Timestamp value={job.finished_at} />
          </li>
        )}
  </>;
}

export function ProcessingOverview({ job, now = null, unconfirmed = false, recoveryAction }: {
  job: ObservedJob; now?: number | null; unconfirmed?: boolean; recoveryAction?: ReactNode;
}) {
  const cutName = job.pipeline_version === "highlight_v1" ? "highlights" : "first cut";
  const progress = !unconfirmed && job.status === "running" ? job.progress : null;
  const stage = progress ? STAGE_COPY[progress.stage] : null;
  const title = unconfirmed ? "We lost touch — showing your last update"
    : job.status === "queued" ? "Waiting to start"
    : job.status === "succeeded" ? `Your ${cutName} ${cutName === "highlights" ? "are" : "is"} ready`
    : job.status === "failed" ? `We couldn’t create your ${cutName}`
    : stage?.title ?? "Creating your video…";
  const description = unconfirmed ? "This is the last update we could confirm. Check again to see where things stand."
    : job.status === "queued" ? "Your video is waiting its turn. We’ll start as soon as we can."
    : job.status === "succeeded" ? `Your ${cutName} ${cutName === "highlights" ? "are" : "is"} ready to watch and refine below.`
    : job.status === "failed" ? failureDescription(job.error_code)
    : stage?.description ?? "Your video is being created. New details will appear here.";
  const count = progress?.completed_windows != null && progress.total_windows != null
    ? `${progress.completed_windows} of ${progress.total_windows} moments checked` : null;

  return <>
      <div className="processing-summary" role="status" aria-live="polite" aria-atomic="true">
        <span className="studio-overline">Creating your video</span>
        <h3>{title}</h3>
        <p>{description}</p>
        {count && <p className="processing-windowCount technical">{count}</p>}
      </div>
      {job.status === "failed" && recoveryAction && <div className="mt-4">{recoveryAction}</div>}
      <dl className="processing-timing">
        <div><dt>Time so far</dt><dd className="technical">{formatElapsed(elapsedSeconds(job, now))}</dd></div>
        <div><dt>Try</dt><dd className="technical">{job.attempt_count}</dd></div>
      </dl>
  </>;
}
