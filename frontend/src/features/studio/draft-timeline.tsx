"use client";

import { DraftPersistence } from "./draft-persistence";
import { useActiveJobId } from "./store/use-editor-store";
import type { CSSProperties } from "react";
import { draftMatchesSaved, useDraftStore, type TimelineDraft } from "./store/use-draft-store";

export function DraftControls({ projectId, draft }: { projectId: string; draft: TimelineDraft }) {
  const { move, remove } = useDraftStore();
  const index = draft.cuts.findIndex((cut) => cut.id === draft.selectedId);
  const cut = draft.cuts[index];
  return <div className="studio-draftActions" role="group" aria-label="Selected cut actions">
    <button type="button" className="button button-secondary" disabled={!cut || index === 0} onClick={() => cut && move(projectId, cut.id, -1)}>Move left</button>
    <button type="button" className="button button-secondary" disabled={!cut || index === draft.cuts.length - 1} onClick={() => cut && move(projectId, cut.id, 1)}>Move right</button>
    <button type="button" className="button button-secondary" disabled={!cut} onClick={() => cut && remove(projectId, cut.id)}>Remove cut</button>
  </div>;
}

export function DraftTimeline({ projectId, draft }: { projectId: string; draft: TimelineDraft }) {
  const { select, undo, redo, acceptPending } = useDraftStore();
  const activeJob = useActiveJobId(projectId);
  const saved = useDraftStore(state => state.savedByProject[projectId]);
  const total = draft.cuts.reduce((sum, cut) => sum + cut.end_seconds - cut.start_seconds, 0);
  return <div className="studio-storyboard" role="region" aria-label="Editing draft">
    <div className="studio-draftToolbar">
      <p className="studio-storyboardSummary" role="status">{draft.cuts.length} cuts · Source duration {total.toFixed(2)}s · Edit {draft.revision} ·
        {draftMatchesSaved(draft,saved) ? `Saved revision ${saved?.revision}` : "Unsaved draft changes"}</p>
      <div className="studio-draftActions" role="group" aria-label="Draft history">
        <button type="button" className="button button-secondary" disabled={!draft.past.length} onClick={() => undo(projectId)}>Undo</button>
        <button type="button" className="button button-secondary" disabled={!draft.future.length} onClick={() => redo(projectId)}>Redo</button>
      </div>
    </div>
    {activeJob && activeJob !== draft.base.jobId && <p className="studio-storyboardNote">Editing previous result {draft.base.jobId.slice(0, 8)}. The selected AI job is shown in AI Story Director.</p>}
    {draft.pending && <div className="studio-draftProposal" role="status"><p>A new AI result is available. Your edits are retained.</p><button type="button" className="button button-secondary" onClick={() => acceptPending(projectId)}>Discard draft and use new AI result</button></div>}
    <DraftPersistence projectId={projectId} draft={draft} />
    <DraftControls projectId={projectId} draft={draft} />
    {!draft.cuts.length ? <p className="studio-storyboardNote" role="status">Draft is empty. Undo to restore a cut. The published video is unchanged.</p> : <ol className="studio-cutList" aria-label="Draft playback order" style={{
      "--cut-tracks": draft.cuts.map((cut) => `${cut.end_seconds - cut.start_seconds}fr`).join(" "),
      "--sequence-min-width": `${total * 76}px`,
    } as CSSProperties}>
      {draft.cuts.map((cut, index) => <li key={cut.id} className={`studio-cut${draft.selectedId === cut.id ? " studio-cutSelected" : ""}`}>
        <button type="button" className="studio-cutSelect" aria-pressed={draft.selectedId === cut.id} aria-label={`Select Cut ${index + 1}`} onClick={() => select(projectId, cut.id)}>
          <span className="studio-cutHeading"><span>Cut {index + 1}{draft.selectedId === cut.id ? " · Selected" : ""}</span><span className="technical">{(cut.end_seconds - cut.start_seconds).toFixed(2)}s</span></span>
          <span>Source: {cut.start_seconds.toFixed(2)}s – {cut.end_seconds.toFixed(2)}s</span>
          <span className="studio-cutMedia">Media: {cut.media_id ?? "Not supplied"}</span>
        </button>
      </li>)}
    </ol>}
    <p className="studio-storyboardNote">Select a cut to inspect its source. Reordering changes this draft only. Program Monitor plays the selected rendered version. Unsaved changes do not modify that MP4.</p>
  </div>;
}
