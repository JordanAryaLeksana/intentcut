"use client";

import { useEditingScope } from "../workflow";
import { DraftPersistence } from "../draft-persistence";
import { useActiveJobId } from "../store/use-editor-store";
import { useDraftStore } from "../store/use-draft-store";
import { formatTimestamp } from "./highlight-format";

/** Sidebar sequence controls; the lower workspace is reserved for previewing AI discoveries. */
export function HighlightSelectedStory({ projectId }: { projectId: string }) {
  const { scope } = useEditingScope(projectId);
  const draft = useDraftStore(state => state.byProject[scope]);
  const activeJobId = useActiveJobId(projectId);
  const { move, remove, undo, redo, acceptPending } = useDraftStore();
  if (!draft) return null;
  const total = draft.cuts.reduce((sum, cut) => sum + cut.end_seconds - cut.start_seconds, 0);

  return <section className="highlight-selectedStory" aria-label="Your selected story">
    <div className="highlight-selectedStoryHeader">
      <h3>Your selected story</h3>
      <span>{draft.cuts.length} moments · {total.toFixed(1)}s</span>
    </div>
    <p className="highlight-note">These clips play from top to bottom in your next video. Use ↑ and ↓ to change the order, or Remove to leave one out.</p>
    <div className="studio-draftActions" role="group" aria-label="Undo and redo Highlights changes">
      <button type="button" className="button button-secondary" disabled={!draft.past.length} onClick={() => undo(scope)}>Undo</button>
      <button type="button" className="button button-secondary" disabled={!draft.future.length} onClick={() => redo(scope)}>Redo</button>
    </div>
    {activeJobId && activeJobId !== draft.base.jobId && <p className="highlight-note">This sequence is from an earlier Highlights job. Your newer job is still available.</p>}
    {draft.pending && <div className="studio-draftProposal" role="status">
      <p>A newer version is ready; your current changes are preserved.</p>
      <button type="button" className="button button-secondary" onClick={() => acceptPending(scope)}>Discard these edits and use the newer story</button>
    </div>}
    <ol className="highlight-selectedStoryOrder" aria-label="Selected moments in playback order">
      {draft.cuts.map((cut, index) => <li key={cut.id}>
        <div className="highlight-selectedStoryCut">
          <strong>Moment {index + 1}</strong>
          <span>{(cut.end_seconds - cut.start_seconds).toFixed(1)}s</span>
        </div>
        <span className="highlight-selectedStoryTime">{formatTimestamp(cut.start_seconds)}–{formatTimestamp(cut.end_seconds)}</span>
        <div className="studio-draftActions">
          <button type="button" className="button button-secondary" disabled={index === 0} aria-label={`Move moment ${index + 1} earlier`} onClick={() => move(scope, cut.id, -1)}>↑</button>
          <button type="button" className="button button-secondary" disabled={index === draft.cuts.length - 1} aria-label={`Move moment ${index + 1} later`} onClick={() => move(scope, cut.id, 1)}>↓</button>
          <button type="button" className="button button-secondary" aria-label={`Remove moment ${index + 1}`} onClick={() => remove(scope, cut.id)}>Remove</button>
        </div>
      </li>)}
    </ol>
    {!draft.cuts.length && <p role="status">Your sequence is empty. Undo to restore a moment.</p>}
    <p className="highlight-note">Your current MP4 does not change until you save these edits and choose Make my video. Rendering this draft does not repeat AI discovery.</p>
    <DraftPersistence projectId={projectId} draft={draft} />
  </section>;
}
