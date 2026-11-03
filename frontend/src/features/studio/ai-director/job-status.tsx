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
      {query.isPending && !query.isError && <p role="status">Checking on your video…</p>}
      {query.isError && (
        <div className="processing-queryError" role="alert">
          <p>We couldn’t check on your video. It may still be on its way — your footage is unchanged.</p>
          <button type="button" className="button button-secondary" onClick={() => void query.refetch()}>Check again</button>
        </div>
      )}
      {job && <ProcessingTimeline job={job} now={now} unconfirmed={query.isError} />}
      {job?.status === "succeeded" && !query.isError && <JobArtifacts projectId={projectId} jobId={jobId} />}
    </div>
  );
}
