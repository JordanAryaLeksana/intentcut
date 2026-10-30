"use client";

import { useQuery } from "@tanstack/react-query";
import { listAIArtifacts } from "@/lib/api/artifacts";

export const aiArtifactsKey = (
  projectId: string,
  jobId: string,
) =>
  [
    "projects",
    projectId,
    "ai-jobs",
    jobId,
    "artifacts",
  ] as const;

export function useAIArtifacts(
  projectId: string,
  jobId: string,
) {
  return useQuery({
    queryKey: aiArtifactsKey(projectId, jobId),

    queryFn: ({ signal }) =>
      listAIArtifacts(projectId, jobId, signal),

    enabled: Boolean(projectId && jobId),

    retry: 1,

    staleTime: 30_000,

    refetchOnWindowFocus: false,
  });
}