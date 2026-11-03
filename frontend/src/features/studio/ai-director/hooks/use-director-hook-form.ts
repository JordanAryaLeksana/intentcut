
"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { listAIJobs } from "@/lib/api/ai-jobs";
import { ApiError, canonicalId } from "@/lib/api/transport";
import {
  latestRecoverableJobId,
  readSavedJobId,
  removeSavedJobId,
  writeSavedJobId,
} from "../../store/job-recovery";
import { useProjectMedia } from "../../media/hooks/use-project-media";
import { useSelectedMediaIds,useEditorStore, useActiveJobId } from "../../store/use-editor-store";
import { useCreateAIJob } from "./use-create-ai-job";
import { useAIJobStatus } from "./use-ai-job-status";

export function useDirectorForm(projectId: string) {
  // Local form state
  const [intent, setIntent] = useState("");
  const [duration, setDuration] = useState("30");

  const [uncertain, setUncertain] = useState(false);

  const submitLock = useRef(false);

  // Shared state and server state
  const selectedMediaIds = useSelectedMediaIds(projectId);
  const mediaQuery = useProjectMedia(projectId);
  const createJob = useCreateAIJob(projectId);

  // Validate selected media against persisted project media
  const savedIds = new Set(
    mediaQuery.data?.map((media) => media.id) ?? [],
  );
  const jobId = useActiveJobId(projectId);

  const setActiveJob = useEditorStore(
    (state) => state.setActiveJob,
  );
  const clearActiveJob = useEditorStore(
    (state) => state.clearActiveJob,
  );
  const rejectedJob = useRef<string | null>(null);
  const jobStatus = useAIJobStatus(projectId, jobId);
  // Server fallback for reopen/restart when session storage has no job.
  // Read-only: adopting never creates, claims, or mutates a job.
  const recovery = useQuery({
    queryKey: ["projects", projectId, "ai-jobs", "recoverable-list"] as const,
    queryFn: ({ signal }) => listAIJobs(projectId, signal),
    enabled: Boolean(projectId && !jobId),
    retry: false,
    staleTime: 0,
  });

  useEffect(() => {
    // Never overwrite a job already accepted in this session.
    if (useEditorStore.getState().activeJobByProject[projectId]) return;
    try {
      const savedId = readSavedJobId(projectId, window.sessionStorage);
      if (savedId) setActiveJob(projectId, savedId);
    } catch {
      // Access to sessionStorage itself can be blocked by the browser.
    }
  }, [projectId, setActiveJob]);

  useEffect(() => {
    if (!recovery.isSuccess || submitLock.current || createJob.isPending) return;
    if (useEditorStore.getState().activeJobByProject[projectId]) return;
    const candidate = latestRecoverableJobId(
      recovery.data.filter(
        (job) => canonicalId(job.id) !== (rejectedJob.current ?? ""),
      ),
    );
    if (!candidate) return;
    setActiveJob(projectId, candidate);
    try {
      writeSavedJobId(projectId, window.sessionStorage, candidate);
    } catch {
      // Session storage may be unavailable; the server list re-adopts.
    }
  }, [recovery.isSuccess, recovery.data, createJob.isPending, projectId, setActiveJob]);

  useEffect(() => {
    // A definitive 404 means the remembered job is gone (deleted or from
    // another database). Forget it so reopening cannot block forever.
    // Transient 5xx/network errors keep the job: it may still exist.
    if (!jobId || !jobStatus.isError) return;
    const error = jobStatus.error;
    if (!(error instanceof ApiError) || error.status !== 404) return;
    rejectedJob.current = canonicalId(jobId);
    clearActiveJob(projectId);
    try {
      removeSavedJobId(projectId, window.sessionStorage);
    } catch {
      // In-memory clear above already unblocks this session.
    }
  }, [jobId, jobStatus.isError, jobStatus.error, projectId, clearActiveJob]);
  const selectionValid =
    mediaQuery.isSuccess &&
    selectedMediaIds.length > 0 &&
    selectedMediaIds.every((id) => savedIds.has(id));

  // Validate creative brief and duration
  const trimmedIntent = intent.trim();
  const targetSeconds = Number(duration);

  const formValid =
    trimmedIntent.length >= 1 &&
    trimmedIntent.length <= 1000 &&
    duration.trim() !== "" &&
    Number.isFinite(targetSeconds) &&
    targetSeconds > 0 &&
    targetSeconds <= 120;

  const canSubmit =
    selectionValid &&
    formValid &&
    !createJob.isPending &&
    !jobId &&
    !uncertain;

  async function submit(): Promise<void> {
    if (!canSubmit || submitLock.current) return;

    submitLock.current = true;

    try {
      const accepted = await createJob.mutateAsync({
        kind: "first_cut",
        intent: trimmedIntent,
        target_seconds: targetSeconds,
        media_ids: [...selectedMediaIds],
      });

      setActiveJob(projectId, accepted.id);
      writeSavedJobId(projectId, sessionStorage, accepted.id);
    } catch (error) {
      // The backend may have accepted the job before
      // the browser received its response.
      if (
        !(error instanceof ApiError) ||
        error.status === 0 ||
        error.status >= 500
      ) {
        setUncertain(true);
      }
    } finally {
      submitLock.current = false;
    }
  }

  function resumeLastJob(): void {
    try {
      const savedId = readSavedJobId(projectId, sessionStorage);
      if (savedId) {
        setActiveJob(projectId, savedId);
      }
    } catch {
      // Session storage may be disabled.
    }
  }

  function acknowledgeUncertain(): void {
    createJob.reset();
    setUncertain(false);
  }

  return {
    // Form
    intent,
    setIntent,
    duration,
    setDuration,
    canSubmit,
    submit,

    // Selection
    selectedCount: selectedMediaIds.length,
    selectionValid,
    mediaLoading: mediaQuery.isPending,
    mediaError: mediaQuery.error,

    // Mutation
    isSubmitting: createJob.isPending,
    submitError: createJob.error,
    uncertain,
    acknowledgeUncertain,

    // Job recovery
    jobId,
    resumeLastJob,
  };
}
