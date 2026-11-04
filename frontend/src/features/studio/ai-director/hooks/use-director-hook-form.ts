"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listAIJobs } from "@/lib/api/ai-jobs";
import type { FirstCutRequest } from "@/lib/api/contracts";
import { ApiError } from "@/lib/api/transport";
import { writeSavedJobId } from "../../store/job-recovery";
import { useProjectMedia } from "../../media/hooks/use-project-media";
import { useSelectedMediaIds, useEditorStore, useActiveJobId } from "../../store/use-editor-store";
import { isProcessing, readFirstCutRequest, recoveryJob, saveFirstCutRequest, validFirstCutRequest } from "../first-cut-recovery";
import { useCreateAIJob } from "./use-create-ai-job";
import { useAIJobStatus } from "./use-ai-job-status";

export const directorJobsKey = (projectId: string) => ["projects", projectId, "ai-jobs", "recoverable-list"] as const;

export function useDirectorForm(projectId: string) {
  const [form, setForm] = useState<{ jobId: string | null; intent?: string; duration?: string }>({ jobId: null });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const submitLock = useRef(false);
  const acceptedHere = useRef<string | null>(null);
  const client = useQueryClient();
  const selectedMediaIds = useSelectedMediaIds(projectId);
  const mediaQuery = useProjectMedia(projectId);
  const createJob = useCreateAIJob(projectId);
  const jobId = useActiveJobId(projectId);
  const setActiveJob = useEditorStore(state => state.setActiveJob);
  const clearActiveJob = useEditorStore(state => state.clearActiveJob);
  const jobStatus = useAIJobStatus(projectId, jobId);
  const recovery = useQuery({
    queryKey: directorJobsKey(projectId),
    queryFn: ({ signal }) => listAIJobs(projectId, signal),
    retry: false, staleTime: 0,
  });

  function adopt(id: string) {
    setActiveJob(projectId, id);
    try { writeSavedJobId(projectId, window.sessionStorage, id); } catch { /* Optional storage. */ }
  }

  useEffect(() => {
    if (!recovery.isSuccess || submitLock.current) return;
    // A just-accepted job may not yet be in an older list response.
    if (acceptedHere.current && !recovery.data.some(job => job.id === acceptedHere.current)) return;
    const candidate = recoveryJob(recovery.data);
    if (candidate) {
      setActiveJob(projectId, candidate.id);
      try { writeSavedJobId(projectId, window.sessionStorage, candidate.id); } catch { /* Optional storage. */ }
    } else clearActiveJob(projectId);
  }, [recovery.data, recovery.isSuccess, projectId, setActiveJob, clearActiveJob]);

  const original = useQuery({
    queryKey: ["projects", projectId, "first-cut-inputs", jobId],
    queryFn: () => jobId ? readFirstCutRequest(projectId, jobId) : null,
    enabled: Boolean(jobId), staleTime: Infinity,
  });
  const retryRequest = original.data ?? null;
  const intent = (form.jobId === jobId ? form.intent : undefined) ?? retryRequest?.intent ?? "";
  const duration = (form.jobId === jobId ? form.duration : undefined) ?? String(retryRequest?.target_seconds ?? 30);
  const setIntent = (value: string) => setForm({ jobId, intent: value, duration });
  const setDuration = (value: string) => setForm({ jobId, intent, duration: value });
  useEffect(() => {
    if (!retryRequest) return;
    useEditorStore.setState(state => ({ selectedMediaByProject: {
      ...state.selectedMediaByProject, [projectId]: [...retryRequest.media_ids],
    } }));
  }, [projectId, retryRequest]);

  const savedIds = new Set(mediaQuery.data?.map(media => media.id) ?? []);
  const inputsAvailable = (request: FirstCutRequest) => mediaQuery.isSuccess &&
    request.media_ids.every(id => savedIds.has(id));
  const request: FirstCutRequest = { kind: "first_cut", intent: intent.trim(), target_seconds: Number(duration), media_ids: [...selectedMediaIds] };
  const selectionValid = mediaQuery.isSuccess && selectedMediaIds.length > 0 &&
    selectedMediaIds.length <= 10 && selectedMediaIds.every(id => savedIds.has(id));
  const busy = isProcessing(jobStatus.data) || recovery.data?.some(job => job.id !== jobId && isProcessing(job));
  const blocked = isSubmitting || Boolean(busy) || uncertain || !recovery.isSuccess ||
    Boolean(jobId && (!jobStatus.isSuccess || jobStatus.data.id !== jobId));
  const failed = jobStatus.data?.status === "failed";
  const canRetry = Boolean(failed && retryRequest && inputsAvailable(retryRequest) && !blocked);
  const canSubmit = !blocked && validFirstCutRequest(request) && inputsAvailable(request);

  async function submit(retry = false): Promise<void> {
    const payload = retry ? retryRequest : request;
    if (submitLock.current || !(retry ? canRetry : canSubmit) || !payload) return;
    submitLock.current = true;
    setIsSubmitting(true);
    setSubmitError(false);
    let posting = false;
    try {
      // Recheck server work immediately before POST (including work from another tab).
      const jobs = await listAIJobs(projectId);
      client.setQueryData(directorJobsKey(projectId), jobs);
      const active = jobs.find(isProcessing);
      if (active) { adopt(active.id); return; }
      posting = true;
      const accepted = await createJob.mutateAsync(payload);
      acceptedHere.current = accepted.id;
      saveFirstCutRequest(projectId, accepted.id, payload);
      adopt(accepted.id);
      void recovery.refetch();
    } catch (error) {
      setSubmitError(true);
      if (posting && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500)) {
        setUncertain(true);
      }
    } finally {
      submitLock.current = false;
      setIsSubmitting(false);
    }
  }

  async function checkRecovery() {
    const result = await recovery.refetch();
    if (!result.isSuccess) return;
    const candidate = recoveryJob(result.data);
    if (candidate && candidate.id !== jobId) { adopt(candidate.id); setUncertain(false); }
  }

  return {
    intent, setIntent, duration, setDuration, canSubmit, submit,
    selectedCount: selectedMediaIds.length, selectionValid,
    mediaLoading: mediaQuery.isPending, mediaError: mediaQuery.error,
    isSubmitting, submitError, uncertain, jobId, failed, canRetry,
    inputsMissing: failed && (!retryRequest || (mediaQuery.isSuccess && !inputsAvailable(retryRequest))),
    formDisabled: blocked, recoveryError: recovery.isError, checkRecovery,
    jobs: recovery.data ?? [],
  };
}
