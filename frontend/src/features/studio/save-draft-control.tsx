"use client";

import { useEditingScope } from "./workflow";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import { getSavedDraft } from "@/lib/api/editing";
import { draftMatchesSaved, useDraftStore } from "./store/use-draft-store";
import { savedDraftKey } from "./use-editing";
import { useSaveDraft } from "./use-save-draft";

export function DraftSaveStatus({ projectId }: { projectId: string }) {
  const { scope } = useEditingScope(projectId);
  const draft = useDraftStore(s => s.byProject[scope]);
  const saved = useDraftStore(s => s.savedByProject[scope]);
  const save = useSaveDraft(projectId);
  return <span className="studio-draftState" role="status">{save.pending ? "Saving…" : save.error ? "Save failed" : !draft ? "No draft yet" : draftMatchesSaved(draft, saved) ? `All changes saved · Version ${saved?.revision}` : "Unsaved changes"}</span>;
}

export function SaveDraftControl({ projectId, showStatus = false }: { projectId: string; showStatus?: boolean }) {
  const { workflow, scope } = useEditingScope(projectId);
  const draft = useDraftStore(s => s.byProject[scope]);
  const saved = useDraftStore(s => s.savedByProject[scope]);
  const restored = useDraftStore(s => s.restoredByProject[scope]);
  const save = useSaveDraft(projectId);
  const client = useQueryClient();
  const [reloading, setReloading] = useState(false);
  const [reloadError, setReloadError] = useState(false);
  const matches = Boolean(draft && draftMatchesSaved(draft, saved));
  async function reload() {
    if (reloading || save.pending) return;
    setReloading(true);
    setReloadError(false);
    try {
      const result = await getSavedDraft(projectId, undefined, workflow);
      useDraftStore.getState().restore(scope, result, true);
      client.setQueryData(savedDraftKey(projectId, workflow), result);
      save.reset();
    } catch { setReloadError(true); }
    finally { setReloading(false); }
  }
  return <div className="studio-saveControl">
    {showStatus && <DraftSaveStatus projectId={projectId} />}
    <button id={(workflow === "first_cut" ? "editing-draft-save" : "editing-draft-save-highlights")} type="button" className="button button-primary" disabled={!draft || !restored || matches || save.pending || reloading}
      onClick={() => { void save.save().catch(() => {}); }}>{save.pending ? "Saving…" : save.error ? "Retry Save Changes" : "Save Changes"}</button>
    {Boolean(save.error) && <div className="studio-saveError" role="alert">
      <p>{save.error instanceof ApiError && save.error.status === 409 ? "A newer editing draft is saved. Your local edits are kept. Reload the saved draft before saving again." : "Save failed. Your local edits are kept. Retry Save Changes, or reload the saved draft."}</p>
      <button type="button" className="button button-secondary" disabled={save.pending || reloading} onClick={() => void reload()}>{reloading ? "Reloading…" : "Discard my edits and show the saved draft"}</button>
    </div>}
    {reloadError && <p role="alert">We couldn’t reload your editing draft. Your local edits are kept. Try reloading again.</p>}
  </div>;
}
