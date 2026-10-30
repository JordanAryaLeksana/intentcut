"use client";

import { queryOptions, useQuery } from "@tanstack/react-query";

import { getAIJob } from "@/lib/api/ai-jobs";
import { ApiError } from "@/lib/api/transport";
import { observeJob, type ObservedJob } from "../processing-state";

export function jobPollingInterval(status?: string, error?: unknown): number | false {
  if (status && status !== "queued" && status !== "running") return false;
  if (error) {
    const transient = error instanceof ApiError && (error.status >= 500 || error.code === "network_error");
    if (!transient || !status) return false;
  }
  return 2_000;
}

export const aiJobKey = (
  projectId: string,
  jobId: string | null,
) => ["projects", projectId, "ai-jobs", jobId] as const;

export function aiJobStatusOptions(
  projectId: string,
  jobId: string | null,
) {
  return queryOptions({
    queryKey: aiJobKey(projectId, jobId),

    queryFn: async ({ signal, client }) => {
      if (!jobId) {
        throw new Error("AI job ID is required.");
      }

      const response = await getAIJob(projectId, jobId, signal);
      return observeJob(client.getQueryData<ObservedJob>(aiJobKey(projectId, jobId)), response);
    },

    enabled: Boolean(projectId && jobId),

    retry: false,
    retryOnMount: false,

    staleTime: 0,

    refetchOnWindowFocus: true,

    refetchIntervalInBackground: false,

    refetchInterval: (query) => {
      return jobPollingInterval(query.state.data?.status, query.state.error);
    },
  });
}

export function useAIJobStatus(projectId: string, jobId: string | null) {
  return useQuery(aiJobStatusOptions(projectId, jobId));
}
