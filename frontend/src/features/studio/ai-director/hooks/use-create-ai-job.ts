"use client";

import { useMutation } from "@tanstack/react-query";

import { createAIJob } from "@/lib/api/ai-jobs";
import type { FirstCutRequest } from "@/lib/api/contracts";

export function useCreateAIJob(projectId: string) {
  return useMutation({
    mutationKey: ["projects", projectId, "ai-jobs", "create"],

    mutationFn: (payload: FirstCutRequest) =>
      createAIJob(projectId, payload),

    retry: false,
  });
}