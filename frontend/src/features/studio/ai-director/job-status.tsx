"use client";

import { useAIJobStatus } from "./hooks/use-ai-job-status";
import { JobArtifacts } from "./job-artifacts";
import { ProcessingTimeline, useProcessingClock } from "./processing-timeline";

export function JobStatus({ projectId, jobId }: { projectId: string; jobId: string }) {
  const query = useAIJobStatus(projectId, jobId);
  const job = query.data;
  const now = useProcessingClock(job?.status === "queued" || job?.status === "running");

  return (
    <div className="studio-processingJob">
      {query.isPending && !query.isError && <p role="status">Checking job status…</p>}
      {query.isError && (
        <div className="processing-queryError" role="alert">
          <p>Could not refresh this job. It may be unavailable or temporarily unreachable.</p>
          <button type="button" className="button button-secondary" onClick={() => void query.refetch()}>Refresh status</button>
        </div>
      )}
      {job && <ProcessingTimeline job={job} now={now} unconfirmed={query.isError} />}
      {job?.status === "succeeded" && !query.isError && <JobArtifacts projectId={projectId} jobId={jobId} />}
    </div>
  );
}
