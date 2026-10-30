"use client";

import { queryOptions, useQuery } from "@tanstack/react-query";
import { getSavedDraft, listRenderVersions } from "@/lib/api/editing";
import { useDraftStore } from "./store/use-draft-store";
import { useActiveJobId } from "./store/use-editor-store";

export const savedDraftKey = (projectId: string) => ["projects", projectId, "edit-draft"] as const;
export const renderVersionsKey = (projectId: string) => ["projects", projectId, "edit-renders"] as const;
export const savedDraftOptions = (projectId: string) => queryOptions({
  queryKey: savedDraftKey(projectId), queryFn: ({ signal }) => getSavedDraft(projectId, signal),
  retry: false, staleTime: Infinity, refetchOnWindowFocus: false,
});
export const renderVersionsOptions = (projectId: string) => queryOptions({
  queryKey: renderVersionsKey(projectId), queryFn: ({ signal }) => listRenderVersions(projectId, signal),
  retry: false, refetchOnWindowFocus: true,
  refetchInterval: (query) => query.state.error ? false : query.state.data?.some(v => v.status === "queued" || v.status === "running") ? 2000 : false,
});
export function useRenderVersions(projectId: string) { return useQuery(renderVersionsOptions(projectId)); }
export function usePreviewJob(projectId: string) {
  const versions = useRenderVersions(projectId);
  const selected = useDraftStore(state => state.previewByProject[projectId]);
  const original = useActiveJobId(projectId);
  const saved = useDraftStore(state => state.savedByProject[projectId]);
  const manual = selected === undefined ? versions.data?.find(v => v.status === "succeeded")?.job_id : selected;
  return { jobId: manual ?? original ?? saved?.base_job_id ?? null, manual: manual ? versions.data?.find(v => v.job_id === manual) : undefined, versions };
}
