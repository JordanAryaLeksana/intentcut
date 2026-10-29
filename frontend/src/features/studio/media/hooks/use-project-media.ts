"use client";

import { useQuery } from "@tanstack/react-query";
import { listAllMedia } from "@/lib/api/media";

export const projectMediaKey = (projectId: string) =>
  ["projects", projectId, "media"] as const;

export function useProjectMedia(projectId: string) {
  return useQuery({
    queryKey: projectMediaKey(projectId),

    queryFn: ({ signal }) =>
      listAllMedia(projectId, signal),

    enabled: Boolean(projectId),

    staleTime: 30_000,
  });
}