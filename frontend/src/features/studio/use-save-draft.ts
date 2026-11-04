"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { saveDraft } from "@/lib/api/editing";
import { savedDraftKey } from "./use-editing";
import { draftMatchesSaved, useDraftStore } from "./store/use-draft-store";

type SaveState = { pending: boolean; error: unknown };
const idle: SaveState = { pending: false, error: null };
const useSaveState = create<{ projects: Record<string, SaveState> }>(() => ({ projects: {} }));
const pending = new Map<string, Promise<void>>();

function setSaveState(projectId: string, state: SaveState) {
  useSaveState.setState(current => ({ projects: { ...current.projects, [projectId]: state } }));
}

/** One save per project across the header, timeline and Director, including same-tick clicks. */
export function persistEditingDraft(client: QueryClient, projectId: string): Promise<void> {
  const existing = pending.get(projectId);
  if (existing) return existing;
  const state = useDraftStore.getState();
  const draft = state.byProject[projectId];
  const saved = state.savedByProject[projectId];
  if (!draft || !state.restoredByProject[projectId] || draftMatchesSaved(draft, saved)) return Promise.resolve();
  // Snapshot the sequence and expected server revision before the user can keep editing.
  const body = { expected_revision: saved?.revision ?? 0, base_job_id: draft.base.jobId,
    base_artifact_id: draft.base.artifactId, window_indices: draft.cuts.map(c => c.window_index) };
  setSaveState(projectId, { pending: true, error: null });
  const operation = Promise.resolve().then(async () => {
    await client.cancelQueries({ queryKey: savedDraftKey(projectId) });
    const result = await saveDraft(projectId, body);
    // Only acknowledge persisted content. Never replace edits made during the request.
    useDraftStore.getState().saved(projectId, result);
    client.setQueryData(savedDraftKey(projectId), result);
    setSaveState(projectId, idle);
  }).catch(error => {
    setSaveState(projectId, { pending: false, error });
    throw error;
  }).finally(() => { pending.delete(projectId); });
  pending.set(projectId, operation);
  return operation;
}

export function useSaveDraft(projectId: string) {
  const client = useQueryClient();
  const state = useSaveState(s => s.projects[projectId] ?? idle);
  return { ...state, save: () => persistEditingDraft(client, projectId),
    reset: () => setSaveState(projectId, idle) };
}
