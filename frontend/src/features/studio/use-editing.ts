"use client";

import { useEffect } from "react";
import { useEditingScope } from "./workflow";
import type { EditingWorkflow } from "@/lib/api/workflow";
import { isProjectId } from "@/lib/api/transport";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { aiJobKey } from "./ai-director/hooks/use-ai-job-status";
import { aiArtifactsKey } from "./ai-director/hooks/use-ai-artifacts";
import { getSavedDraft, listRenderVersions, type RenderVersion } from "@/lib/api/editing";
import { useDraftStore } from "./store/use-draft-store";
import { useActiveJobId } from "./store/use-editor-store";

export const savedDraftKey = (projectId: string, workflow: EditingWorkflow = "first_cut") => ["projects", projectId, "edit-draft", ...(workflow === "first_cut" ? [] : [workflow])] as const;
export const renderVersionsKey = (projectId: string, workflow: EditingWorkflow = "first_cut") => ["projects", projectId, "edit-renders", ...(workflow === "first_cut" ? [] : [workflow])] as const;
export const savedDraftOptions = (projectId: string, workflow: EditingWorkflow = "first_cut") => queryOptions({
  queryKey: savedDraftKey(projectId, workflow), queryFn: ({ signal }) => getSavedDraft(projectId, signal, workflow),
  retry: false, staleTime: Infinity, refetchOnWindowFocus: false,
});
export const renderVersionsOptions = (projectId: string, workflow: EditingWorkflow = "first_cut") => queryOptions({
  queryKey: renderVersionsKey(projectId, workflow), queryFn: async ({ signal, client }) => {
    const previous = client.getQueryData<RenderVersion[]>(renderVersionsKey(projectId, workflow));
    const next = await listRenderVersions(projectId, signal, workflow);
    for (const version of next) {
      const before = previous?.find(v => v.job_id === version.job_id);
      if (before && before.status !== version.status) {
        void client.invalidateQueries({ queryKey: aiJobKey(projectId, version.job_id), exact: true });
        if (version.status === "succeeded") void client.invalidateQueries({ queryKey: aiArtifactsKey(projectId, version.job_id) });
      }
    }
    return next;
  },
  retry: false, refetchOnWindowFocus: true,
  refetchInterval: (query) => query.state.data?.some(v => v.status === "queued" || v.status === "running") ? 2000 : false,
});
export function useRenderVersions(projectId: string) { const { workflow } = useEditingScope(projectId); return useQuery(renderVersionsOptions(projectId, workflow)); }
export function usePreviewJob(projectId: string) {
  const { scope } = useEditingScope(projectId);
  const versions = useRenderVersions(projectId);
  const selected = useDraftStore(state => state.previewByProject[scope]);
  useEffect(() => {
    if (useDraftStore.getState().previewByProject[scope] !== undefined) return;
    try {
      const raw = sessionStorage.getItem(`intentcut:preview:${scope}`);
      if (raw === null) return;
      const value: unknown = JSON.parse(raw);
      if (value === null || (typeof value === "string" && isProjectId(value))) useDraftStore.getState().setPreview(scope, value);
    } catch { /* Optional session persistence. */ }
  }, [scope]);
  const active = useActiveJobId(projectId);
  const draft = useDraftStore(state => state.byProject[scope]);
  const original = draft?.base.jobId ?? active;
  const saved = useDraftStore(state => state.savedByProject[scope]);
  // Automatic selection shows the newest *ready* version (newest first), so a
  // queued/running render never replaces a playable video. Before any version
  // is ready, the generated cut stays on screen.
  const manual = selected === undefined ? versions.data?.find(v => v.status === "succeeded")?.job_id : selected;
  return { jobId: manual ?? original ?? saved?.base_job_id ?? null, manual: manual ? versions.data?.find(v => v.job_id === manual) : undefined, versions };
}
