"use client";

import { create } from "zustand";
import type { SavedDraft } from "@/lib/api/editing";
import type { PublicStoryboard, PublicStoryboardCut } from "../ai-director/storyboard/storyboard-schema";

export interface DraftCut extends PublicStoryboardCut { id: string }
export interface DraftBase { jobId: string; artifactId: string }
interface Snapshot { cuts: DraftCut[]; selectedId: string | null }
export interface TimelineDraft extends Snapshot {
  base: DraftBase;
  publishedCuts: DraftCut[];
  revision: number;
  past: Snapshot[];
  future: Snapshot[];
  pending?: { base: DraftBase; storyboard: PublicStoryboard };
}
export function createDraft(base: DraftBase, storyboard: PublicStoryboard): TimelineDraft {
  const cuts = storyboard.cuts.map((cut) => ({ ...cut, id: `${base.artifactId}:${cut.window_index}` }));
  return { base, cuts, publishedCuts: cuts, selectedId: null, revision: 0, past: [], future: [] };
}
export function isDraftDirty(draft: TimelineDraft): boolean {
  return draft.cuts.length !== draft.publishedCuts.length || draft.cuts.some((cut, i) => cut.id !== draft.publishedCuts[i]?.id);
}
export function draftMatchesSaved(draft: TimelineDraft, saved?: SavedDraft | null): boolean {
  return Boolean(saved && draft.base.jobId === saved.base_job_id && draft.base.artifactId === saved.base_artifact_id &&
    draft.cuts.length === saved.window_indices.length && draft.cuts.every((cut, index) => cut.window_index === saved.window_indices[index]));
}
interface DraftState {
  byProject: Record<string, TimelineDraft>;
  savedByProject: Record<string, SavedDraft | null>;
  restoredByProject: Record<string, boolean>;
  previewByProject: Record<string, string | null>;
  setPreview: (projectId: string, jobId: string | null) => void;
  restore: (projectId: string, saved: SavedDraft | null, force?: boolean) => void;
  saved: (projectId: string, saved: SavedDraft) => void;
  applyAccepted: (projectId: string, saved: SavedDraft, expectedLocalRevision: number) => void;
  dockTabByProject: Record<string, "director" | "inspector">;
  setDockTab: (projectId: string, tab: "director" | "inspector") => void;
  receive: (projectId: string, base: DraftBase, storyboard: PublicStoryboard) => void;
  acceptPending: (projectId: string) => void;
  select: (projectId: string, id: string) => void;
  move: (projectId: string, id: string, direction: -1 | 1) => void;
  remove: (projectId: string, id: string) => void;
  undo: (projectId: string) => void;
  redo: (projectId: string) => void;
}
function snapshot(draft: TimelineDraft): Snapshot { return { cuts: draft.cuts, selectedId: draft.selectedId }; }
function edit(draft: TimelineDraft, next: Snapshot): TimelineDraft {
  return { ...draft, ...next, revision: draft.revision + 1, past: [...draft.past, snapshot(draft)], future: [] };
}
export const useDraftStore = create<DraftState>()((set) => {
  const update = (projectId: string, fn: (draft: TimelineDraft) => TimelineDraft) => set((state) => {
    const draft = state.byProject[projectId];
    if (!draft) return state;
    const next = fn(draft);
    return next === draft ? state : { byProject: { ...state.byProject, [projectId]: next } };
  });
  return {
    byProject: {},
    savedByProject: {}, restoredByProject: {}, previewByProject: {},
    setPreview: (projectId, jobId) => set((state) => ({ previewByProject: {...state.previewByProject, [projectId]: jobId} })),
    applyAccepted: (projectId, saved, expectedLocalRevision) => set((state) => {
      const current = state.byProject[projectId];
      let next = current;
      if (current && current.revision === expectedLocalRevision && current.base.jobId === saved.base_job_id && current.base.artifactId === saved.base_artifact_id) {
        const allowed = new Map(current.publishedCuts.map(c => [c.window_index,c]));
        const cuts = saved.window_indices.flatMap(i => {const cut = allowed.get(i);return cut ? [cut] : [];});
        next = edit(current,{cuts,selectedId:cuts.some(c=>c.id===current.selectedId)?current.selectedId:null});
      }
      return { savedByProject:{...state.savedByProject,[projectId]:saved}, byProject:next ? {...state.byProject,[projectId]:next} : state.byProject };
    }),
    saved: (projectId, saved) => set((state) => ({savedByProject: {...state.savedByProject, [projectId]: saved}})),
    restore: (projectId, saved, force = false) => set((state) => {
      if (state.restoredByProject[projectId] && !force) return state;
      const next = { ...state.byProject };
      if (saved && (force || !next[projectId])) {
        const draft = createDraft({jobId:saved.base_job_id, artifactId:saved.base_artifact_id}, saved.storyboard);
        const allowed = new Map(draft.cuts.map(c => [c.window_index, c]));
        draft.cuts = saved.window_indices.flatMap(i => {const cut = allowed.get(i); return cut ? [cut] : [];});
        next[projectId] = draft;
      }
      return { byProject:next, savedByProject:{...state.savedByProject, [projectId]:saved}, restoredByProject:{...state.restoredByProject,[projectId]:true} };
    }),
    dockTabByProject: {},
    setDockTab: (projectId, tab) => set((state) => ({ dockTabByProject: { ...state.dockTabByProject, [projectId]: tab } })),
    receive: (projectId, base, storyboard) => set((state) => {
      const current = state.byProject[projectId];
      if (current?.base.jobId === base.jobId && current.base.artifactId === base.artifactId) return state;
      if (current?.pending?.base.jobId === base.jobId && current.pending.base.artifactId === base.artifactId) return state;
      const next = current && isDraftDirty(current)
        ? { ...current, pending: { base, storyboard } }
        : createDraft(base, storyboard);
      return { byProject: { ...state.byProject, [projectId]: next } };
    }),
    acceptPending: (projectId) => update(projectId, (d) => d.pending ? createDraft(d.pending.base, d.pending.storyboard) : d),
    select: (projectId, id) => set((state) => {
      const draft = state.byProject[projectId];
      if (!draft?.cuts.some((c) => c.id === id)) return state;
      return { byProject: { ...state.byProject, [projectId]: { ...draft, selectedId: id } }, dockTabByProject: { ...state.dockTabByProject, [projectId]: "inspector" } };
    }),
    move: (projectId, id, direction) => update(projectId, (d) => {
      const index = d.cuts.findIndex((c) => c.id === id), target = index + direction;
      const cut = d.cuts[index], neighbor = d.cuts[target];
      if (!cut || !neighbor) return d;
      const cuts = [...d.cuts]; cuts[index] = neighbor; cuts[target] = cut;
      return edit(d, { cuts, selectedId: id });
    }),
    remove: (projectId, id) => update(projectId, (d) => {
      const index = d.cuts.findIndex((c) => c.id === id);
      if (index < 0) return d;
      const cuts = d.cuts.filter((c) => c.id !== id);
      return edit(d, { cuts, selectedId: d.selectedId === id ? (cuts[index] ?? cuts[index - 1])?.id ?? null : d.selectedId });
    }),
    undo: (projectId) => update(projectId, (d) => {
      const previous = d.past.at(-1);
      return previous ? { ...d, ...previous, revision: d.revision + 1, past: d.past.slice(0, -1), future: [...d.future, snapshot(d)] } : d;
    }),
    redo: (projectId) => update(projectId, (d) => {
      const next = d.future.at(-1);
      return next ? { ...d, ...next, revision: d.revision + 1, past: [...d.past, snapshot(d)], future: d.future.slice(0, -1) } : d;
    }),
  };
});
