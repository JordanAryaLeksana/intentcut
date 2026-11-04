"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { create } from "zustand";
import { useDraftStore } from "./store/use-draft-store";
import { workflowScope, type EditingWorkflow } from "@/lib/api/workflow";

const WorkflowContext = createContext<EditingWorkflow>("first_cut");
const useWorkflows = create<{ selected: Record<string, EditingWorkflow>; choose: (id: string, value: EditingWorkflow) => void }>(set => ({
  selected: {}, choose: (id, value) => {
    try { sessionStorage.setItem(`intentcut:workflow:${id}`, value); } catch { /* Optional preference. */ }
    set(state => ({ selected: { ...state.selected, [id]: value } }));
  },
}));
export function WorkflowBoundary({ workflow, children }: { workflow: EditingWorkflow; children: ReactNode }) {
  return <WorkflowContext value={workflow}>{children}</WorkflowContext>;
}
export function StudioWorkflow({ projectId, children }: { projectId?: string; children: ReactNode }) {
  const workflow = useWorkflows(state => state.selected[projectId ?? ""] ?? "first_cut");
  useEffect(() => {
    if (!projectId) return;
    try { if (sessionStorage.getItem(`intentcut:workflow:${projectId}`) === "highlights") useWorkflows.getState().choose(projectId, "highlights"); } catch { /* Optional preference. */ }
  }, [projectId]);
  return <WorkflowBoundary workflow={workflow}>{children}</WorkflowBoundary>;
}
export function useEditingScope(projectId: string) {
  const workflow = useContext(WorkflowContext);
  return { workflow, scope: workflowScope(projectId, workflow) };
}
export function WorkflowSwitcher({ projectId }: { projectId: string }) {
  const { workflow } = useEditingScope(projectId);
  const choose = useWorkflows(state => state.choose);
  return <fieldset className="studio-workflowSwitch"><legend className="sr-only">Editing workflow</legend>
    {(["first_cut", "highlights"] as const).map(value => <button type="button" key={value} aria-pressed={workflow === value} onClick={() => { choose(projectId, value); useDraftStore.getState().setDockTab(workflowScope(projectId, value), value === "highlights" ? "highlights" : "director"); }}>{value === "first_cut" ? "AI First Cut" : "AI Highlights"}</button>)}
  </fieldset>;
}

export const selectWorkflow = (projectId: string, workflow: EditingWorkflow) => useWorkflows.getState().choose(projectId, workflow);
