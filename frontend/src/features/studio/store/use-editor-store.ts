"use client";

import { create } from "zustand";

export const MAX_AI_MEDIA_SELECTION = 4;

interface EditorState {
  selectedMediaByProject: Record<string, string[]>;

  toggleMediaSelection: (projectId: string, mediaId: string) => void;

  clearMediaSelection: (projectId: string) => void;
  activeJobByProject: Record<string, string>;

  setActiveJob: (projectId: string, jobId: string) => void;
}

const EMPTY_SELECTION: string[] = [];

export const useEditorStore = create<EditorState>()((set) => ({
  selectedMediaByProject: {},

  toggleMediaSelection: (projectId, mediaId) =>
    set((state) => {
      const current = state.selectedMediaByProject[projectId] ?? [];

      const alreadySelected = current.includes(mediaId);

      if (!alreadySelected && current.length >= MAX_AI_MEDIA_SELECTION) {
        return state;
      }

      const next = alreadySelected
        ? current.filter((id) => id !== mediaId)
        : [...current, mediaId];

      return {
        selectedMediaByProject: {
          ...state.selectedMediaByProject,
          [projectId]: next,
        },
      };
    }),

  clearMediaSelection: (projectId) =>
    set((state) => ({
      selectedMediaByProject: {
        ...state.selectedMediaByProject,
        [projectId]: [],
      },
    })),
  activeJobByProject: {},

  setActiveJob: (projectId, jobId) =>
    set((state) => ({
      activeJobByProject: {
        ...state.activeJobByProject,
        [projectId]: jobId,
      },
    })),
}));

export function useSelectedMediaIds(projectId: string) {
  return useEditorStore(
    (state) => state.selectedMediaByProject[projectId] ?? EMPTY_SELECTION,
  );
}
export function useActiveJobId(projectId: string) {
  return useEditorStore(
    (state) => state.activeJobByProject[projectId] ?? null,
  );
}
