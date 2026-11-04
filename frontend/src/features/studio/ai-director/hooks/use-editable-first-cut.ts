"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AIJob } from "@/lib/api/contracts";
import { useDraftStore } from "../../store/use-draft-store";
import { savedDraftOptions } from "../../use-editing";
import { useAIJobStatus } from "./use-ai-job-status";
import { useAIArtifacts } from "./use-ai-artifacts";
import { usePublicStoryboard } from "./use-public-storyboard";

/** Verify the draft's own successful job and artifacts, independently of the latest attempt. */
export function useEditableFirstCut(projectId: string, activeJobId: string | null, jobs: AIJob[]) {
  const saved = useQuery(savedDraftOptions(projectId));
  const draft = useDraftStore(state => state.byProject[projectId]);
  const restore = useDraftStore(state => state.restore);
  const receive = useDraftStore(state => state.receive);
  const active = useAIJobStatus(projectId, activeJobId);
  const jobId = draft?.base.jobId ?? saved.data?.base_job_id ??
    (active.data?.status === "succeeded" ? activeJobId : jobs.find(job => job.status === "succeeded")?.id) ?? null;
  const job = useAIJobStatus(projectId, jobId);
  const artifacts = useAIArtifacts(projectId, job.data?.status === "succeeded" ? jobId ?? "" : "");
  const requiredId = draft?.base.artifactId ?? saved.data?.base_artifact_id;
  const storyboardArtifact = artifacts.data?.items.find(item => item.kind === "storyboard" && (!requiredId || item.id === requiredId));
  const video = artifacts.data?.items.some(item => item.kind === "video" && item.size_bytes > 0);
  const storyboard = usePublicStoryboard(projectId, jobId ?? "", storyboardArtifact?.id ?? "", Boolean(video && storyboardArtifact));
  const ready = job.data?.status === "succeeded" && video && Boolean(storyboard.data?.cuts.length);

  useEffect(() => {
    if (saved.isSuccess) restore(projectId, saved.data);
  }, [saved.isSuccess, saved.data, projectId, restore]);

  useEffect(() => {
    // Recover an unsaved published draft too, without overwriting local edits.
    if (saved.isSuccess && !draft && ready && jobId && storyboardArtifact && storyboard.data) {
      receive(projectId, { jobId, artifactId: storyboardArtifact.id }, storyboard.data);
    }
  }, [saved.isSuccess, draft, ready, jobId, storyboardArtifact, storyboard.data, projectId, receive]);

  // Keep draft saving reachable even after the user removes every moment.
  return Boolean(ready && draft && draft.base.jobId === jobId);
}
