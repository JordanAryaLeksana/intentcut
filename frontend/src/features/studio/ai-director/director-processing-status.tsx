"use client";

import { useEditingScope } from "../workflow";
import { Fragment, useEffect, useRef, type ReactNode } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useRenderVersions } from "../use-editing";
import { aiJobStatusOptions, useAIJobStatus } from "./hooks/use-ai-job-status";
import { JobArtifacts } from "./job-artifacts";
import { proposalOptions } from "./revision-chat";
import { buildLifecyclePhases } from "./processing-lifecycle";
import { FirstCutMilestones, ProcessingOverview, Timestamp, useProcessingClock } from "./processing-timeline";
import { STAGE_COPY, type ObservedJob } from "./processing-state";

export { activityRenderLabel } from "./processing-lifecycle";

export function DirectorProcessingStatus({ projectId, firstCutJobId, children }: {
  projectId: string; firstCutJobId: string | null; children?: ReactNode;
}) {
  const { workflow } = useEditingScope(projectId);
  const firstLabel = workflow === "highlights" ? "AI Highlights" : "First Cut";
  const headingId = workflow === "first_cut" ? "processing-heading" : "processing-heading-highlights";
  const versions = useRenderVersions(projectId);
  const proposals = useQuery(proposalOptions(projectId, workflow));
  const firstCut = useAIJobStatus(projectId, firstCutJobId);
  const renders = [...new Map((versions.data ?? []).map(v => [v.job_id, v])).values()];
  // Keep the existing single active render detail poll. Historical details are
  // fetched once through the same cache; the render list invalidates transitions.
  const activeRenderId = renders.find(v => v.status === "queued" || v.status === "running")?.job_id;
  const renderJobs = useQueries({ queries: renders.map(version => {
    const options = aiJobStatusOptions(projectId, version.job_id);
    return { ...options, staleTime: version.job_id === activeRenderId ? 0 : Infinity,
      refetchInterval: version.job_id === activeRenderId ? options.refetchInterval : false as const };
  }) });
  const jobs = new Map<string, ObservedJob>();
  renderJobs.forEach(query => { if (query.data) jobs.set(query.data.id, query.data); });
  const phases = buildLifecyclePhases(renders, proposals.data ?? [], jobs);
  const current = phases.findLast(phase => phase.active) ?? phases.at(-1);
  const firstActive = firstCut.data?.status === "queued" || firstCut.data?.status === "running";
  const now = useProcessingClock(firstActive);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const latestKey = `${projectId}:${current?.id ?? firstCutJobId}:${current?.status ?? firstCut.data?.status}:${phases.length}`;
  useEffect(() => {
    const region = scrollRegion.current;
    if (region && followLatest.current) region.scrollTop = region.scrollHeight;
  }, [latestKey]);
  const firstOnly = !phases.length;
  const errors = new Set(renders.filter((_, index) => renderJobs[index].isError).map(v => v.job_id));
  const unconfirmed = versions.isError || proposals.isError || (current && errors.has(current.id));

  return <section aria-labelledby={headingId} className="processing-lifecycle mb-6">
    <div className="processing-lifecycleHeading">
      <h3 id={headingId}>Video Activity</h3>
      {!firstOnly && <button type="button" className="processing-jump" onClick={() => {
        const region = scrollRegion.current;
        if (region) { region.scrollTop = region.scrollHeight; region.focus(); followLatest.current = true; }
      }}>Latest update ↓</button>}
    </div>
    <div className="studio-processingJob">
      {firstOnly && firstCut.data && <ProcessingOverview job={firstCut.data} now={now} unconfirmed={firstCut.isError} recoveryAction={children} />}
      {current && <div className="processing-summary processing-current" role="status" aria-live="polite" aria-atomic="true">
        <span className="studio-overline">{current.active && !unconfirmed ? "In progress" : "Latest update"}</span>
        <h3>{current.label} · {current.status}</h3>
        {unconfirmed && <p>Showing the last confirmed update.</p>}
      </div>}
      {versions.isPending && <p role="status">Loading video activity…</p>}
      {proposals.isPending && <p role="status">Loading revision history…</p>}
      {firstCutJobId && firstCut.isPending && <p role="status">Checking on {firstLabel}…</p>}
      {versions.isError && <p className="processing-queryError" role="alert">Video activity could not be refreshed. Displayed status is last confirmed. <button type="button" onClick={() => void versions.refetch()}>Check video activity</button></p>}
      {proposals.isError && <p className="processing-queryError" role="alert">Revision history could not be refreshed. <button type="button" onClick={() => void proposals.refetch()}>Check revision history</button></p>}
      {firstCutJobId && firstCut.isError && <p className="processing-queryError" role="alert">{firstLabel} details could not be refreshed. <button type="button" onClick={() => void firstCut.refetch()}>Check {firstLabel}</button></p>}
      {(firstCut.data || phases.length > 0) && <div className="processing-history" ref={scrollRegion} tabIndex={0} role="region" aria-label="Project processing timeline" onScroll={event => {
        const region = event.currentTarget;
        followLatest.current = region.scrollHeight - region.scrollTop - region.clientHeight < 32;
      }}>
        <ol className="processing-milestones" aria-label="How your video is coming along">
          {firstCut.data && <FirstCutMilestones job={firstCut.data} unconfirmed={firstCut.isError} label={firstLabel} />}
          {phases.map(phase => {
            const stale = (renders.some(v => v.job_id === phase.id) ? versions.isError : proposals.isError) || errors.has(phase.id);
            return <Fragment key={phase.id}>
              {phase.steps.map((step, index) => <li key={`${phase.id}:${step.key}`} data-phase={phase.id} data-step={step.key}
                data-state={stale && (step.state === "active" || step.state === "waiting") ? "unknown" : step.state}
                data-current={current?.id === phase.id && phase.active && !stale || undefined}
                aria-current={current?.id === phase.id && step.state === "active" && !stale ? "step" : undefined}>
                {index === 0 && <p className="processing-phaseLabel">{phase.label}</p>}
                <h4>{step.title}</h4>
                <Timestamp value={step.timestamp} />
                {step.description && !(stale && step.progress) && <p>{step.description}</p>}
                {step.progress && !stale && <p>Stage started <Timestamp value={step.progress.stage_started_at} /></p>}
                {index === 0 && phase.instruction && <details className="processing-instruction"><summary>Revision request</summary><p>{phase.instruction}</p></details>}
                {index === phase.steps.length - 1 && <details className="processing-jobId"><summary>Details for support</summary><p className="technical">{phase.id}</p></details>}
              </li>)}
            </Fragment>;
          })}
        </ol>
      </div>}
      {errors.size > 0 && <p className="processing-queryError" role="alert">Some progress details are unavailable. <button type="button" onClick={() => { renderJobs.forEach(query => { if (query.isError) void query.refetch(); }); }}>Check progress details</button></p>}
      {firstCut.data?.status === "failed" && <>
        {!firstOnly && children}
        {firstCut.data.lastObservedProgress && <p className="processing-lastStage">Last step we saw: {STAGE_COPY[firstCut.data.lastObservedProgress.stage].title}. That alone doesn’t tell us why it stopped.</p>}
      </>}
      {firstCut.data?.status === "succeeded" && !firstCut.isError && <>
        {firstOnly && <a className="button button-primary processing-viewCut" href="#monitor-heading">Watch your video</a>}
        <details className="processing-jobId"><summary>{firstLabel} files &amp; details</summary>
          <p className="technical">{firstCutJobId}</p>
          <JobArtifacts projectId={projectId} jobId={firstCut.data.id} />
        </details>
      </>}
      {!firstCutJobId && firstOnly && versions.isSuccess && proposals.isSuccess && <p className="processing-empty">Your processing timeline will appear here when you create {workflow === "highlights" ? "AI Highlights" : "a First Cut"}.</p>}
    </div>
  </section>;
}
