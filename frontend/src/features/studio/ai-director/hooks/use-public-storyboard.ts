
"use client";

import { queryOptions, useQuery } from "@tanstack/react-query";

import { loadAIArtifactJSON } from "@/lib/api/artifacts";
import { parsePublicStoryboard } from "../storyboard/storyboard-schema";

export function publicStoryboardOptions(
  projectId: string,
  jobId: string,
  artifactId: string,
  enabled: boolean,
) {
  return queryOptions({
    queryKey: [
      "projects",
      projectId,
      "ai-jobs",
      jobId,
      "artifacts",
      artifactId,
      "public-storyboard",
    ] as const,

    queryFn: async ({ signal }) => {
      const payload = await loadAIArtifactJSON(
        projectId,
        jobId,
        artifactId,
        signal,
      );

      return parsePublicStoryboard(payload);
    },

    enabled:
      enabled &&
      Boolean(projectId && jobId && artifactId),

    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function usePublicStoryboard(projectId: string, jobId: string, artifactId: string, enabled: boolean) {
  return useQuery(publicStoryboardOptions(projectId, jobId, artifactId, enabled));
}
