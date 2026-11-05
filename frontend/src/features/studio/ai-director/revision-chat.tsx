"use client";

import { useEditingScope } from "../workflow";

import { workflowScope, type EditingWorkflow } from "@/lib/api/workflow";
import { useRef, useState } from "react";
import { create } from "zustand";
import {
  queryOptions,
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import { getSavedDraft } from "@/lib/api/editing";
import {
  decideProposal,
  listProposals,
  requestRevision,
  type RevisionProposal,
} from "@/lib/api/revisions";
import { draftMatchesSaved, draftSyncState, useDraftStore } from "../store/use-draft-store";
import { draftSaveLabel, SaveDraftControl } from "../save-draft-control";
import { persistEditingDraft, useSaveDraft } from "../use-save-draft";
import { savedDraftKey } from "../use-editing";

export const proposalsKey = (projectId: string, workflow: EditingWorkflow = "first_cut") =>
  ["projects", projectId, "revision-proposals", ...(workflow === "first_cut" ? [] : [workflow])] as const;
export const proposalOptions = (projectId: string, workflow: EditingWorkflow = "first_cut") =>
  queryOptions({
    queryKey: proposalsKey(projectId, workflow),
    queryFn: ({ signal }) => listProposals(projectId, signal, workflow),
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      query.state.data?.some(
              (p) => p.job_status === "queued" || p.job_status === "running",
            )
          ? 2000
          : false,
  });
export function proposalStatus(proposal: RevisionProposal): string {
  if (proposal.state === "accepted")
    return `Done · Saved as version ${proposal.applied_revision} · Make a new video to watch it`;
  if (proposal.state === "rejected")
    return "Turned down · Your draft is unchanged";
  if (proposal.state === "stale")
    return "Out of date · Your saved draft changed — ask for a fresh idea";
  if (proposal.state === "failed")
    return proposal.error_code === "unsupported_revision"
      ? "We can only reorder or remove moments for now · Your draft is unchanged"
      : proposal.error_code === "provider_unavailable"
        ? "The AI service is unavailable · Your draft is unchanged"
        : "That idea didn’t work · Your draft is unchanged";
  if (proposal.job_status === "queued") return "Waiting to start";
  if (proposal.job_status === "running")
    return proposal.progress?.stage === "revising_sequence"
      ? "Your AI Director is reworking the order"
      : "Reworking your story…";
  return "Ready for you · Nothing changes until you say yes";
}

export function ProposalReview({
  projectId,
  proposal,
}: {
  projectId: string;
  proposal: RevisionProposal;
}) {
  const { workflow, scope } = useEditingScope(projectId);
  const client = useQueryClient();
  const saved = useDraftStore((s) => s.savedByProject[scope]);
  const draft = useDraftStore((s) => s.byProject[scope]);
  const { applyAccepted, restore } = useDraftStore();
  const [reloadError, setReloadError] = useState(false);
  const aligned = Boolean(
    saved &&
    draft &&
    draftMatchesSaved(draft, saved) &&
    saved.revision === proposal.base_revision &&
    draft.base.jobId === proposal.base_job_id &&
    draft.base.artifactId === proposal.base_artifact_id,
  );
  const decide = useMutation({
    mutationFn: async (accept: boolean) => {
      const current = useDraftStore.getState().byProject[scope];
      if (accept && (!aligned || !current))
        throw new Error("Save or reload the current draft before acceptance.");
      const localRevision = current?.revision ?? -1;
      const result = await decideProposal(
        projectId,
        proposal.id,
        accept ? proposal.base_revision : null,
        workflow,
      );
      return { ...result, localRevision };
    },
    retry: false,
    onSuccess: (result) => {
      if (result.draft) {
        applyAccepted(scope, result.draft, result.localRevision);
        client.setQueryData(savedDraftKey(projectId, workflow), result.draft);
      }
      void client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
  });
  async function reload() {
    setReloadError(false);
    try {
      const value = await getSavedDraft(projectId, undefined, workflow);
      restore(scope, value, true);
      client.setQueryData(savedDraftKey(projectId, workflow), value);
    } catch {
      setReloadError(true);
    }
  }
  const pending = proposal.state === "pending";
  const ready =
    pending && proposal.job_status === "succeeded" && proposal.after !== null;
  return (
    <article className="revision-message">
      <p className="studio-overline">You · Version {proposal.base_revision}</p>
      <p className="revision-instruction">{proposal.instruction}</p>
      <p role="status">{proposalStatus(proposal)}</p>
      {proposal.after && (
        <>
          <p className="studio-overline">AI Director · Why this order?</p>
          <p>{proposal.explanation}</p>
          <div className="revision-comparison">
            <div>
              <h4>Your order now</h4>
              <ol>
                {proposal.before.map((id, index) => (
                  <li key={id}>Moment {index + 1}</li>
                ))}
              </ol>
            </div>
            <div>
              <h4>Suggested order</h4>
              <ol>
                {proposal.after.map((id) => (
                  <li key={id}>Moment {proposal.before.indexOf(id) + 1}</li>
                ))}
              </ol>
            </div>
          </div>
          <p>
            {proposal.changes.removed.length} moment
            {proposal.changes.removed.length === 1 ? "" : "s"} removed ·{" "}
            {proposal.changes.reordered ? "Order changed" : "Same order kept"}
          </p>
          <ul className="revision-reasons">
            {proposal.reasons.map((r) => (
              <li key={r.window_index}>
                <strong>
                  Moment {proposal.before.indexOf(r.window_index) + 1}:
                </strong>{" "}
                {r.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {pending && (
        <div className="studio-draftActions">
          {ready && (
            <button
              type="button"
              className="button button-primary"
              disabled={!aligned || decide.isPending}
              onClick={() => decide.mutate(true)}
            >
              Use this order
            </button>
          )}
          <button
            type="button"
            className="button button-secondary"
            disabled={decide.isPending}
            onClick={() => decide.mutate(false)}
          >
            {ready ? "No thanks" : "Cancel request"}
          </button>
        </div>
      )}
      {ready && !aligned && (
        <p>
          Your draft changed since you asked. Save your edits, or look at the
          saved draft, before using this idea.
        </p>
      )}
      {decide.isError && (
        <div role="alert">
          <p>
            {decide.error instanceof ApiError && decide.error.status === 409
              ? "Your draft changed. What you edited here is kept."
              : "We couldn’t confirm that. Look above before trying again."}
          </p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reload()}
          >
            Discard my edits and show the saved draft
          </button>
        </div>
      )}
      {reloadError && (
        <p role="alert">
          We couldn’t reload the saved draft. What you edited here is kept.
        </p>
      )}
      {proposal.state === "accepted" &&
        saved?.revision !== proposal.applied_revision && (
          <div>
            <p>Your new order is saved. Reload to see it here.</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reload()}
            >
              Discard my edits and show the saved draft
            </button>
          </div>
        )}
      {proposal.state === "accepted" && (
        <p>
          Make a new video from this order in Timeline. Any newer edits you made
          stay separate.
        </p>
      )}
    </article>
  );
}

/**
 * Typed-but-unsent revision instructions, keyed by editing scope. Shared so the
 * render controls can warn that "Make my video" will not include a request the
 * AI Director has never seen. Cleared only when the request is accepted by the
 * server (or the user clears the field).
 */
export const useRevisionInstruction = create<{
  byScope: Record<string, string>;
  /** A send was attempted but its outcome is unknown (e.g. lost response). */
  unconfirmedByScope: Record<string, boolean>;
}>(() => ({ byScope: {}, unconfirmedByScope: {} }));
function setRevisionInstruction(scope: string, value: string) {
  useRevisionInstruction.setState((state) => ({
    byScope: { ...state.byScope, [scope]: value },
    // Editing the text makes it a new, clearly unsent request.
    unconfirmedByScope: { ...state.unconfirmedByScope, [scope]: false },
  }));
}
function markRevisionUnconfirmed(scope: string) {
  useRevisionInstruction.setState((state) => ({ unconfirmedByScope: { ...state.unconfirmedByScope, [scope]: true } }));
}

export type RevisionNotice = "unsent" | "unconfirmed" | "awaiting_decision" | "in_progress";
export const REVISION_NOTICE_COPY: Record<RevisionNotice, string> = {
  unconfirmed:
    "We couldn’t confirm whether your last change request reached your AI Director. Check Rework your story before asking again.",
  unsent:
    "Your change request in Rework your story hasn’t been sent. Make my video uses the order shown here, not that request.",
  awaiting_decision:
    "An AI Director suggestion is waiting for your answer. It isn’t in this order until you choose Use this order.",
  in_progress:
    "Your AI Director is still working on a request. This order doesn’t include it yet.",
};
/** Revision work that the current order does NOT include, most urgent first. */
export function pendingRevisionNotices(
  unsentInstruction: string | undefined,
  proposals: RevisionProposal[] | undefined,
  unconfirmed = false,
): RevisionNotice[] {
  const notices: RevisionNotice[] = [];
  const pending = (proposals ?? []).filter((p) => p.state === "pending");
  if (pending.some((p) => p.job_status === "queued" || p.job_status === "running"))
    notices.push("in_progress");
  if (pending.some((p) => p.job_status === "succeeded" && p.after !== null))
    notices.push("awaiting_decision");
  // Never claim "not sent" when a send was attempted and its outcome is unknown.
  if (unsentInstruction?.trim()) notices.push(unconfirmed ? "unconfirmed" : "unsent");
  return notices;
}

type RevisionRequestBody = { request_id: string; draft_revision: number; instruction: string };
/**
 * Sends one revision request against the persisted draft. An untouched
 * generated cut is first persisted as the base draft (no edits, same order) so
 * the request has a revision to apply to. A previous body is reused verbatim
 * when nothing changed, keeping the request idempotent across manual retries.
 */
export async function sendRevisionRequest(
  client: QueryClient,
  projectId: string,
  workflow: EditingWorkflow,
  instruction: string,
  remembered: { current: RevisionRequestBody | null },
): Promise<string> {
  const scope = workflowScope(projectId, workflow);
  const state = useDraftStore.getState();
  if (draftSyncState(state.byProject[scope], state.savedByProject[scope]) === "original")
    await persistEditingDraft(client, projectId, workflow);
  const after = useDraftStore.getState();
  const base = after.savedByProject[scope];
  const current = after.byProject[scope];
  if (!base || !current || !draftMatchesSaved(current, base))
    throw new Error("Save the draft before requesting a revision.");
  const text = instruction.trim();
  const previous = remembered.current;
  // Remember the body before the network call: if the response is lost, the
  // user's manual retry reuses the same request_id instead of starting twice.
  remembered.current = previous && previous.draft_revision === base.revision && previous.instruction === text
    ? previous
    : { request_id: crypto.randomUUID(), draft_revision: base.revision, instruction: text };
  return requestRevision(projectId, remembered.current, workflow);
}

export function RevisionChat({ projectId }: { projectId: string }) {
  const { workflow, scope } = useEditingScope(projectId);
  const instruction = useRevisionInstruction((s) => s.byScope[scope] ?? "");
  const unconfirmed = useRevisionInstruction((s) => Boolean(s.unconfirmedByScope[scope]));
  const request = useRef<RevisionRequestBody | null>(null);
  const submitLock = useRef(false);
  const save = useSaveDraft(projectId);
  const client = useQueryClient();
  const proposals = useQuery(proposalOptions(projectId, workflow));
  const draft = useDraftStore((s) => s.byProject[scope]);
  const saved = useDraftStore((s) => s.savedByProject[scope]);
  const restored = useDraftStore((s) => s.restoredByProject[scope]);
  const sync = draftSyncState(draft, saved);
  const active = proposals.data?.some(
    (p) => p.job_status === "queued" || p.job_status === "running",
  );
  // An untouched generated cut ("original") can be revised directly: its
  // order is persisted as the base draft just before the request is sent.
  const canSubmit = Boolean(
    restored &&
    draft &&
    draft.cuts.length &&
    (sync === "saved" || sync === "original") &&
    proposals.isSuccess &&
    !active &&
    !save.pending &&
    instruction.trim(),
  );
  const submit = useMutation({
    mutationFn: async () => {
      if (!canSubmit)
        throw new Error("Save the draft before requesting a revision.");
      return sendRevisionRequest(client, projectId, workflow, instruction, request);
    },
    retry: false,
    onSuccess: async () => {
      request.current = null;
      setRevisionInstruction(scope, "");
      await client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
    onError: async () => {
      markRevisionUnconfirmed(scope);
      await client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
    onSettled: () => { submitLock.current = false; },
  });
  const ids = workflow === "first_cut"
    ? { heading: "revision-heading", field: "revision-instruction", hint: "revision-instruction-hint" }
    : { heading: "revision-heading-highlights", field: "revision-instruction-highlights", hint: "revision-instruction-hint-highlights" };
  const unsent = Boolean(instruction.trim()) && !submit.isPending && !unconfirmed;
  // Newest first. The latest request and any still-pending ones stay open;
  // finished older requests are history, collapsed so they never read as the
  // current state of the project.
  const [latest, ...older] = proposals.data ?? [];
  const openOlder = older.filter((p) => p.state === "pending");
  const earlier = older.filter((p) => p.state !== "pending");
  return (
    <section className="studio-revisionChat" aria-labelledby={ids.heading}>
      <h3 id={ids.heading}>Rework your story</h3>
      <p>
        Ask your AI Director to reorder or remove moments. Nothing changes until
        you approve it. Shortening clips, music, transitions, and new footage
        aren’t part of this yet. Your footage stays where it is.
      </p>
      <div className="revision-draftBar">
        <p>
          <span className="studio-overline">Your draft</span>{" "}
          <span className="revision-draftState">{draftSaveLabel(sync, saved?.revision)}</span>
        </p>
        <p className="revision-help">
          Save Changes keeps your Timeline edits. It doesn’t send anything to your AI Director.
        </p>
        <SaveDraftControl projectId={projectId} />
      </div>
      <form
        className="revision-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (submitLock.current || submit.isPending || !canSubmit) return;
          submitLock.current = true;
          submit.mutate();
        }}
      >
        <label htmlFor={ids.field}>What should change?</label>
        <textarea
          id={ids.field}
          rows={3}
          maxLength={1000}
          required
          aria-describedby={ids.hint}
          value={instruction}
          disabled={submit.isPending || active}
          onChange={(event) => setRevisionInstruction(scope, event.target.value)}
          placeholder="Move the last moment first and remove the second one."
        />
        <p id={ids.hint} className="revision-help">
          {instruction.length}/1000 characters ·{" "}
          {sync === "saved"
            ? `Based on saved version ${saved?.revision}`
            : sync === "original"
              ? "Based on your original order"
              : sync === "unsaved"
                ? "Save your edits first"
                : "Create a cut to begin"}
        </p>
        {sync === "unsaved" && (
          <p>Save your edits first, then ask for a new order.</p>
        )}
        {unsent && (
          <p className="revision-unsent">
            Not sent yet. Your AI Director only sees this after you select Ask for a new order.
          </p>
        )}
        {unconfirmed && Boolean(instruction.trim()) && !submit.isPending && (
          <p className="revision-unsent">
            We couldn’t confirm whether this was sent. Check your requests below before asking again.
          </p>
        )}
        <button
          type="submit"
          className="button button-primary"
          disabled={!canSubmit || submit.isPending}
        >
          {submit.isPending ? "Asking…" : "Ask for a new order"}
        </button>
      </form>
      {submit.isError && (
        <p role="alert">
          We couldn’t confirm that. Check below before asking again — asking the
          same thing twice won’t start twice.
        </p>
      )}
      {active && <p role="status">A revision is in progress. Wait for it to finish or cancel the request below.</p>}
      {draft && !draft.cuts.length && <p>Undo a removal in Timeline to restore a moment before requesting a revision.</p>}
      {proposals.isPending && <p role="status">Loading your ideas…</p>}
      {proposals.isError && (
        <p role="alert">
          We couldn’t refresh your ideas. What you see may be out of date.
        </p>
      )}
      <button
        type="button"
        className="button button-secondary"
        onClick={() => void proposals.refetch()}
      >
        Refresh ideas
      </button>
      {latest && <ProposalReview key={latest.id} projectId={projectId} proposal={latest} />}
      {openOlder.map((proposal) => (
        <ProposalReview key={proposal.id} projectId={projectId} proposal={proposal} />
      ))}
      {earlier.length > 0 && (
        <details className="revision-earlier">
          <summary>Earlier requests ({earlier.length})</summary>
          {earlier.map((proposal) => (
            <ProposalReview key={proposal.id} projectId={projectId} proposal={proposal} />
          ))}
        </details>
      )}
    </section>
  );
}
