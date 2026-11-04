"use client";

import { useEditingScope } from "../workflow";

import type { EditingWorkflow } from "@/lib/api/workflow";
import { useRef, useState } from "react";
import {
  queryOptions,
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
import { draftMatchesSaved, useDraftStore } from "../store/use-draft-store";
import { SaveDraftControl } from "../save-draft-control";
import { useSaveDraft } from "../use-save-draft";
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

export function RevisionChat({ projectId }: { projectId: string }) {
  const { workflow, scope } = useEditingScope(projectId);
  const [instruction, setInstruction] = useState("");
  const request = useRef<{
    request_id: string;
    draft_revision: number;
    instruction: string;
  } | null>(null);
  const submitLock = useRef(false);
  const save = useSaveDraft(projectId);
  const client = useQueryClient();
  const proposals = useQuery(proposalOptions(projectId, workflow));
  const draft = useDraftStore((s) => s.byProject[scope]);
  const saved = useDraftStore((s) => s.savedByProject[scope]);
  const active = proposals.data?.some(
    (p) => p.job_status === "queued" || p.job_status === "running",
  );
  const canSubmit = Boolean(
    saved &&
    draft &&
    draft.cuts.length &&
    draftMatchesSaved(draft, saved) &&
    proposals.isSuccess &&
    !active &&
    !save.pending &&
    instruction.trim(),
  );
  const submit = useMutation({
    mutationFn: async () => {
      if (!saved || !canSubmit)
        throw new Error("Save the draft before requesting a revision.");
      if (
        !request.current ||
        request.current.draft_revision !== saved.revision ||
        request.current.instruction !== instruction.trim()
      )
        request.current = {
          request_id: crypto.randomUUID(),
          draft_revision: saved.revision,
          instruction: instruction.trim(),
        };
      return requestRevision(projectId, request.current, workflow);
    },
    retry: false,
    onSuccess: async () => {
      request.current = null;
      setInstruction("");
      await client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
    onError: async () => {
      await client.invalidateQueries({ queryKey: proposalsKey(projectId, workflow) });
    },
    onSettled: () => { submitLock.current = false; },
  });
  return (
    <section className="studio-revisionChat" aria-labelledby={(workflow === "first_cut" ? "revision-heading" : "revision-heading-highlights")}>
      <h3 id={(workflow === "first_cut" ? "revision-heading" : "revision-heading-highlights")}>Rework your story</h3>
      <p>
        Ask your AI Director to reorder or remove moments. Nothing changes until
        you approve it. Shortening clips, music, transitions, and new footage
        aren’t part of this yet. Your footage stays where it is.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (submitLock.current || submit.isPending || !canSubmit) return;
          submitLock.current = true;
          submit.mutate();
        }}
      >
        <label htmlFor={(workflow === "first_cut" ? "revision-instruction" : "revision-instruction-highlights")}>What should change?</label>
        <textarea
          id={(workflow === "first_cut" ? "revision-instruction" : "revision-instruction-highlights")}
          rows={3}
          maxLength={1000}
          required
          value={instruction}
          disabled={submit.isPending || active}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Move the last moment first and remove the second one."
        />
        <p>
          {instruction.length}/1000 characters ·{" "}
          {saved ? `Version ${saved.revision} saved` : "Save a draft to begin"}
        </p>
        {draft && !draftMatchesSaved(draft, saved) && (
          <p>Save your editing draft first, then ask for a new order.</p>
        )}
        <p>Save Changes saves your entire editing draft, including Timeline edits.</p>
        <SaveDraftControl projectId={projectId} />
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
      {proposals.data?.map((proposal) => (
        <ProposalReview
          key={proposal.id}
          projectId={projectId}
          proposal={proposal}
        />
      ))}
    </section>
  );
}
