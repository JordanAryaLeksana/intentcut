"use client";

import { DraftPersistence } from "./draft-persistence";
import { useActiveJobId } from "./store/use-editor-store";
import type { CSSProperties } from "react";
import { draftMatchesSaved, useDraftStore, type TimelineDraft } from "./store/use-draft-store";

export function DraftControls({ projectId, draft }: { projectId: string; draft: TimelineDraft }) {
  const { move, remove } = useDraftStore();
  const index = draft.cuts.findIndex((cut) => cut.id === draft.selectedId);
  const cut = draft.cuts[index];
  return <div className="studio-draftActions" role="group" aria-label="This moment">
    <button type="button" className="button button-secondary" disabled={!cut || index === 0} onClick={() => cut && move(projectId, cut.id, -1)}>Move earlier</button>
    <button type="button" className="button button-secondary" disabled={!cut || index === draft.cuts.length - 1} onClick={() => cut && move(projectId, cut.id, 1)}>Move later</button>
    <button type="button" className="button button-secondary" disabled={!cut} onClick={() => cut && remove(projectId, cut.id)}>Remove moment</button>
  </div>;
}

export function DraftTimeline({ projectId, draft }: { projectId: string; draft: TimelineDraft }) {
  const { select, undo, redo, acceptPending } = useDraftStore();
  const activeJob = useActiveJobId(projectId);
  const saved = useDraftStore(state => state.savedByProject[projectId]);
  const total = draft.cuts.reduce((sum, cut) => sum + cut.end_seconds - cut.start_seconds, 0);
  return <div className="studio-storyboard" role="region" aria-label="Your draft">
    <div className="studio-draftToolbar">
      <p className="studio-storyboardSummary" role="status">{draft.cuts.length} moments · {total.toFixed(1)} seconds ·
        {draftMatchesSaved(draft,saved) ? `Version ${saved?.revision} saved` : "Unsaved changes"}</p>
      <div className="studio-draftActions" role="group" aria-label="Undo and redo">
        <button type="button" className="button button-secondary" disabled={!draft.past.length} onClick={() => undo(projectId)}>Undo</button>
        <button type="button" className="button button-secondary" disabled={!draft.future.length} onClick={() => redo(projectId)}>Redo</button>
      </div>
    </div>
    {activeJob && activeJob !== draft.base.jobId && <p className="studio-storyboardNote">You’re refining an earlier version of your story. Your newest cut is waiting in AI Director.</p>}
    {draft.pending && <div className="studio-draftProposal" role="status"><p>A newer version of your story is ready. What you edited here is kept.</p><button type="button" className="button button-secondary" onClick={() => acceptPending(projectId)}>Discard this draft and use the newer story</button></div>}
    <DraftPersistence projectId={projectId} draft={draft} />
    <DraftControls projectId={projectId} draft={draft} />
    {!draft.cuts.length ? <p className="studio-storyboardNote" role="status">Your draft is empty. Undo to bring a moment back. Your finished video hasn’t changed.</p> : <ol className="studio-cutList" aria-label="Moments in the order they play" style={{
      "--cut-tracks": draft.cuts.map((cut) => `${cut.end_seconds - cut.start_seconds}fr`).join(" "),
      "--sequence-min-width": `${total * 76}px`,
    } as CSSProperties}>
      {draft.cuts.map((cut, index) => <li key={cut.id} className={`studio-cut${draft.selectedId === cut.id ? " studio-cutSelected" : ""}`}>
        <button type="button" className="studio-cutSelect" aria-pressed={draft.selectedId === cut.id} aria-label={`Select Moment ${index + 1}`} onClick={() => select(projectId, cut.id)}>
          <span className="studio-cutHeading"><span>Moment {index + 1}{draft.selectedId === cut.id ? " · Selected" : ""}</span><span className="technical">{(cut.end_seconds - cut.start_seconds).toFixed(1)}s</span></span>
          <span>From your footage: {cut.start_seconds.toFixed(1)}s – {cut.end_seconds.toFixed(1)}s</span>
        </button>
      </li>)}
    </ol>}
    <p className="studio-storyboardNote">Tap a moment to see where it came from. Reordering only changes this draft — your finished video stays as it is until you make a new one.</p>
  </div>;
}
