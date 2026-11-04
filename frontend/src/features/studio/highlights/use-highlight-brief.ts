"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

interface Brief { sourceId: string; intent: string; targetSeconds: number }
const empty: Brief = { sourceId: "", intent: "", targetSeconds: 30 };

/** Keep the creative brief through workflow switches and a browser refresh. */
export function useHighlightBrief(projectId: string) {
  const client = useQueryClient();
  const key = ["projects", projectId, "highlight-brief"] as const;
  const storageKey = `intentcut:highlight-brief:${projectId}`;
  const query = useQuery({ queryKey: key, staleTime: Infinity, queryFn: () => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
      if (value && typeof value.sourceId === "string" && typeof value.intent === "string" &&
          Number.isFinite(value.targetSeconds)) return value as Brief;
    } catch { /* Session storage is optional. */ }
    return empty;
  } });
  return { brief: query.data ?? empty, update: (patch: Partial<Brief>) => {
    const next = { ...(client.getQueryData<Brief>(key) ?? empty), ...patch };
    client.setQueryData(key, next);
    try { sessionStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Optional. */ }
  } };
}
