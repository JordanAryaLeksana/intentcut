"use client";

import { create } from "zustand";
import type { CaptionSet, CueEdit } from "@/lib/api/captions";

export const captionScope = (project: string, video: string, id: string) => `${project}:${video}:${id}`;
export const cueEdits = (set: CaptionSet): CueEdit[] => set.cues.map(({index,text,enabled})=>({index,text,enabled}));
export interface CaptionDraft { saved: CaptionSet; edits: CueEdit[] }
export function captionDirty(draft: CaptionDraft): boolean {
  return JSON.stringify(draft.edits) !== JSON.stringify(cueEdits(draft.saved));
}
export interface CaptionPreview { jobId: string; artifactId: string; label: string }
interface State {
  drafts: Record<string, CaptionDraft>;
  activeByVideo: Record<string, string>;
  previews: Record<string, CaptionPreview | undefined>;
  receive: (scope: string, saved: CaptionSet, force?: boolean) => void;
  change: (scope: string, index: number, patch: Partial<Pick<CueEdit,"text"|"enabled">>) => void;
  saved: (scope: string, saved: CaptionSet) => void;
  preview: (project: string, value?: CaptionPreview) => void;
}
export const useCaptionStore = create<State>()((set) => ({
  drafts:{}, previews:{}, activeByVideo:{},
  receive:(scope,saved,force=false)=>set(state=> {
    if(scope!==captionScope(saved.project_id,saved.parent_artifact_id,saved.id))return state;
    const old = state.drafts[scope];
    const videoKey=`${saved.project_id}:${saved.parent_artifact_id}`;
    const activeByVideo={...state.activeByVideo,[videoKey]:scope};
    if (!force && old && (captionDirty(old) || old.saved.revision >= saved.revision)) return state.activeByVideo[videoKey]===scope ? state : {activeByVideo};
    return {activeByVideo,drafts:{...state.drafts,[scope]:{saved,edits:cueEdits(saved)}}};
  }),
  change:(scope,index,patch)=>set(state=> {
    const old=state.drafts[scope]; if (!old) return state;
    return {drafts:{...state.drafts,[scope]:{...old,edits:old.edits.map(c=>c.index===index?{...c,...patch}:c)}}};
  }),
  saved:(scope,saved)=>set(state=> {
    const old=state.drafts[scope];
    if (!old || scope!==captionScope(saved.project_id,saved.parent_artifact_id,saved.id)
      || saved.revision<old.saved.revision || saved.parent_sha256!==old.saved.parent_sha256) return state;
    // Text changes made during an in-flight save remain unsaved.
    return {drafts:{...state.drafts,[scope]:{saved,edits:old.edits}}};
  }),
  preview:(project,value)=>set(state=>({previews:{...state.previews,[project]:value}})),
}));
