"use client";

import { useQuery } from "@tanstack/react-query";
import { loadAIArtifactJSON } from "@/lib/api/artifacts";

export function useArtifactJSON(
  projectId: string,
  jobId: string,
  artifactId: string,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "projects",
      projectId,
      "ai-jobs",
      jobId,
      "artifacts",
      artifactId,
      "json",
    ] as const,

    queryFn: ({ signal }) =>
      loadAIArtifactJSON(
        projectId,
        jobId,
        artifactId,
        signal,
      ),

    enabled:
      enabled && Boolean(projectId && jobId && artifactId),

    retry: false,
    staleTime: Infinity,
  });
}