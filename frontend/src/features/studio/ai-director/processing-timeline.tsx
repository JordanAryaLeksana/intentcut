"use client";

import { useSyncExternalStore } from "react";
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

function Timestamp({ value }: { value: string | null }) {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return <time dateTime={value} title={value}>{new Date(value).toISOString().slice(11, 19)} UTC</time>;
}

export function ProcessingTimeline({ job, now = null, unconfirmed = false }: {
  job: ObservedJob;
  now?: number | null;
  unconfirmed?: boolean;
}) {
  const terminal = job.status === "succeeded" || job.status === "failed";
  const progress = !unconfirmed && job.status === "running" ? job.progress : null;
  const stage = progress ? STAGE_COPY[progress.stage] : null;
  const title = unconfirmed ? "Status check interrupted"
    : job.status === "queued" ? "Accepted · waiting"
    : job.status === "succeeded" ? "First cut ready"
    : job.status === "failed" ? "First cut failed"
    : stage?.title ?? "Current stage unavailable";
  const description = unconfirmed ? "Showing the last confirmed job update. Refresh to check the current status."
    : job.status === "queued" ? "Your request is queued. Processing has not started."
    : job.status === "succeeded" ? "Processing succeeded. Your generated first cut is ready to review."
    : job.status === "failed" ? failureDescription(job.error_code)
    : stage?.description ?? "The job is marked running, but current processing details are unavailable.";
  const count = progress?.completed_windows != null && progress.total_windows != null
    ? `${progress.completed_windows} of ${progress.total_windows} windows validated` : null;

  return (
    <section className="processing-timeline" aria-label="AI processing timeline">
      <div className="processing-summary" role="status" aria-live="polite" aria-atomic="true">
        <span className="studio-overline">AI processing timeline</span>
        <h3>{title}</h3>
        <p>{description}</p>
        {count && <p className="processing-windowCount technical">{count}</p>}
      </div>
      <dl className="processing-timing">
        <div><dt>Elapsed since accepted</dt><dd className="technical">{formatElapsed(elapsedSeconds(job, now))}</dd></div>
        <div><dt>Attempt</dt><dd className="technical">{job.attempt_count}</dd></div>
      </dl>
      <ol className="processing-milestones" aria-label="Confirmed processing milestones">
        <li data-state="complete">
          <h4>Request accepted</h4><Timestamp value={job.created_at} />
        </li>
        <li data-state={unconfirmed ? "unknown" : job.status === "queued" ? "waiting" : progress ? "active" : job.status === "succeeded" ? "complete" : "unknown"} aria-current={progress ? "step" : undefined}>
          <h4>{job.status === "queued" ? "Waiting for processing" : "Processing attempt"}</h4>
          {job.status === "queued" ? <p>Waiting in the job queue.</p> : <Timestamp value={job.started_at} />}
          {progress && <p>{stage?.title} · Started <Timestamp value={progress.stage_started_at} /></p>}
        </li>
        {terminal && (
          <li data-state={job.status === "succeeded" ? "complete" : "failed"}>
            <h4>{job.status === "succeeded" ? "First cut rendered" : "Attempt failed"}</h4>
            <Timestamp value={job.finished_at} />
          </li>
        )}
      </ol>
      {job.status === "failed" && job.lastObservedProgress && (
        <p className="processing-lastStage">Last reported stage this session: {STAGE_COPY[job.lastObservedProgress.stage].title}. This does not identify the failure cause.</p>
      )}
      {job.status === "succeeded" && !unconfirmed && (
        <a className="button button-primary processing-viewCut" href="#monitor-heading">View first cut</a>
      )}
      <details className="processing-jobId"><summary>Job reference</summary><p className="technical">{job.id}</p></details>
    </section>
  );
}
