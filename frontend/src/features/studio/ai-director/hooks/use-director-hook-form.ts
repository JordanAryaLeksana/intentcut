
"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/transport";
import { readSavedJobId } from "../../store/job-recovery";
import { useProjectMedia } from "../../media/hooks/use-project-media";
import { useSelectedMediaIds,useEditorStore, useActiveJobId } from "../../store/use-editor-store";
import { useCreateAIJob } from "./use-create-ai-job";

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
      try {
        sessionStorage.setItem(
          `intentcut:ai-job:${projectId}`,
          accepted.id,
        );
      } catch {
        // Storage is optional.
      }
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
