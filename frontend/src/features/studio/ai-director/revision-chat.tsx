"use client";

import {useRef,useState} from "react";
import {queryOptions,useMutation,useQuery,useQueryClient} from "@tanstack/react-query";
import {ApiError} from "@/lib/api/transport";
import {getSavedDraft} from "@/lib/api/editing";
import {decideProposal,listProposals,requestRevision,type RevisionProposal} from "@/lib/api/revisions";
import {draftMatchesSaved,useDraftStore} from "../store/use-draft-store";
import {savedDraftKey} from "../use-editing";

export const proposalsKey=(projectId:string)=>["projects",projectId,"revision-proposals"] as const;
export const proposalOptions=(projectId:string)=>queryOptions({queryKey:proposalsKey(projectId),queryFn:({signal})=>listProposals(projectId,signal),retry:false,refetchOnWindowFocus:true,
  refetchInterval:query=>query.state.error?false:query.state.data?.some(p=>p.job_status==="queued"||p.job_status==="running")?2000:false});
export function proposalStatus(proposal:RevisionProposal):string {
  if(proposal.state==="accepted")return `Accepted · Saved revision ${proposal.applied_revision} · Not rendered by this action`;
  if(proposal.state==="rejected")return "Rejected · Draft unchanged";
  if(proposal.state==="stale")return "Stale · Saved draft changed; request a new proposal";
  if(proposal.state==="failed")return proposal.error_code==="unsupported_revision"?"Unsupported request · Only reorder and removal are available":proposal.error_code==="provider_unavailable"?"AI service unavailable · Draft unchanged":"Revision failed validation or processing · Draft unchanged";
  if(proposal.job_status==="queued")return "Request accepted · Waiting for processing";
  if(proposal.job_status==="running")return proposal.progress?.stage==="revising_sequence"?"Muse is preparing a sequence proposal":"Processing revision request";
  return "Proposal ready · Your approval is required";
}

export function ProposalReview({projectId,proposal}:{projectId:string;proposal:RevisionProposal}) {
  const client=useQueryClient();
  const saved=useDraftStore(s=>s.savedByProject[projectId]);
  const draft=useDraftStore(s=>s.byProject[projectId]);
  const {applyAccepted,restore}=useDraftStore();
  const [reloadError,setReloadError]=useState(false);
  const aligned=Boolean(saved&&draft&&draftMatchesSaved(draft,saved)&&saved.revision===proposal.base_revision&&draft.base.jobId===proposal.base_job_id&&draft.base.artifactId===proposal.base_artifact_id);
  const decide=useMutation({mutationFn:async(accept:boolean)=>{
    const current=useDraftStore.getState().byProject[projectId];
    if(accept&&(!aligned||!current))throw new Error("Save or reload the current draft before acceptance.");
    const localRevision=current?.revision??-1;
    const result=await decideProposal(projectId,proposal.id,accept?proposal.base_revision:null);
    return {...result,localRevision};
  },retry:false,onSuccess:result=>{
    if(result.draft){applyAccepted(projectId,result.draft,result.localRevision);client.setQueryData(savedDraftKey(projectId),result.draft);}
    void client.invalidateQueries({queryKey:proposalsKey(projectId)});
  },onError:()=>{void client.invalidateQueries({queryKey:proposalsKey(projectId)});}});
  async function reload(){setReloadError(false);try{const value=await getSavedDraft(projectId);restore(projectId,value,true);client.setQueryData(savedDraftKey(projectId),value);}catch{setReloadError(true);}}
  const pending=proposal.state==="pending";
  const ready=pending&&proposal.job_status==="succeeded"&&proposal.after!==null;
  return <article className="revision-message">
    <p className="studio-overline">Creator · Saved revision {proposal.base_revision}</p>
    <p className="revision-instruction">{proposal.instruction}</p>
    <p role="status">{proposalStatus(proposal)}</p>
    {proposal.after&&<>
      <p className="studio-overline">AI proposal · Editorial reasoning</p><p>{proposal.explanation}</p>
      <div className="revision-comparison"><div><h4>Current at request</h4><ol>{proposal.before.map((id,index)=><li key={id}>Cut {index+1} · Reference {id}</li>)}</ol></div>
        <div><h4>Proposed order</h4><ol>{proposal.after.map(id=><li key={id}>Cut {proposal.before.indexOf(id)+1} · Reference {id}</li>)}</ol></div></div>
      <p>{proposal.changes.removed.length} cut{proposal.changes.removed.length===1?"":"s"} removed · {proposal.changes.reordered?"Playback order changed":"Retained order preserved"}</p>
      <ul className="revision-reasons">{proposal.reasons.map(r=><li key={r.window_index}><strong>Reference {r.window_index}:</strong> {r.reason}</li>)}</ul>
    </>}
    {pending&&<div className="studio-draftActions">
      {ready&&<button type="button" className="button button-primary" disabled={!aligned||decide.isPending} onClick={()=>decide.mutate(true)}>Accept proposal</button>}
      <button type="button" className="button button-secondary" disabled={decide.isPending} onClick={()=>decide.mutate(false)}>{ready?"Reject proposal":"Cancel request"}</button>
    </div>}
    {ready&&!aligned&&<p>Acceptance is blocked because the saved revision or local edits differ. Save your edits or review the saved draft before requesting a new proposal.</p>}
    {decide.isError&&<div role="alert"><p>{decide.error instanceof ApiError&&decide.error.status===409?"Proposal conflict: the draft changed. Your local edits were retained.":"The decision was not confirmed. Refresh proposals before retrying."}</p><button type="button" className="button button-secondary" onClick={()=>void reload()}>Discard local edits and reload saved draft</button></div>}
    {reloadError&&<p role="alert">Could not reload the saved draft. Local edits were retained.</p>}
    {proposal.state==="accepted"&&saved?.revision!==proposal.applied_revision&&<div><p>The accepted revision is stored on the server. Reload it to synchronize this workspace.</p><button type="button" className="button button-secondary" onClick={()=>void reload()}>Discard local edits and reload accepted draft</button></div>}
    {proposal.state==="accepted"&&<p>Use the timeline’s Render Updated Cut action to produce a video from the saved revision. Any newer local edits remain separate.</p>}
  </article>;
}

export function RevisionChat({projectId}:{projectId:string}) {
  const [instruction,setInstruction]=useState("");
  const request=useRef<{request_id:string;draft_revision:number;instruction:string}|null>(null);
  const client=useQueryClient();
  const proposals=useQuery(proposalOptions(projectId));
  const draft=useDraftStore(s=>s.byProject[projectId]);
  const saved=useDraftStore(s=>s.savedByProject[projectId]);
  const active=proposals.data?.some(p=>p.job_status==="queued"||p.job_status==="running");
  const canSubmit=Boolean(saved&&draft&&draft.cuts.length&&draftMatchesSaved(draft,saved)&&proposals.isSuccess&&!active&&instruction.trim());
  const submit=useMutation({mutationFn:async()=>{
    if(!saved||!canSubmit)throw new Error("Save the draft before requesting a revision.");
    if(!request.current||request.current.draft_revision!==saved.revision||request.current.instruction!==instruction.trim())request.current={request_id:crypto.randomUUID(),draft_revision:saved.revision,instruction:instruction.trim()};
    return requestRevision(projectId,request.current);
  },retry:false,onSuccess:()=>{request.current=null;setInstruction("");void client.invalidateQueries({queryKey:proposalsKey(projectId)});},onError:()=>{void client.invalidateQueries({queryKey:proposalsKey(projectId)});}});
  return <section className="studio-revisionChat" aria-labelledby="revision-heading">
    <h3 id="revision-heading">Revise the saved sequence</h3>
    <p>Ask Muse Spark to reorder or remove current cuts. Proposals require your approval. Trimming, music, transitions and new footage are unsupported. No footage is uploaded for this request.</p>
    <form onSubmit={event=>{event.preventDefault();submit.mutate();}}>
      <label htmlFor="revision-instruction">Revision instruction</label>
      <textarea id="revision-instruction" rows={3} maxLength={1000} required value={instruction} disabled={submit.isPending||active} onChange={event=>setInstruction(event.target.value)} placeholder="Move the last cut first and remove the second cut." />
      <p>{instruction.length}/1000 characters · {saved?`Saved revision ${saved.revision}`:"Save a draft to begin"}</p>
      {draft&&!draftMatchesSaved(draft,saved)&&<p>Save your manual changes before requesting a revision.</p>}
      <button type="submit" className="button button-primary" disabled={!canSubmit||submit.isPending}>{submit.isPending?"Submitting request…":"Request AI proposal"}</button>
    </form>
    {submit.isError&&<p role="alert">Revision request was not confirmed. Check the request history before retrying. An unchanged retry uses the same request identifier.</p>}
    {proposals.isPending&&<p role="status">Loading revision requests…</p>}
    {proposals.isError&&<p role="alert">Could not refresh revision requests. Cached proposals may be out of date.</p>}
    <button type="button" className="button button-secondary" onClick={()=>void proposals.refetch()}>Refresh proposals</button>
    {proposals.data?.map(proposal=><ProposalReview key={proposal.id} projectId={projectId} proposal={proposal} />)}
  </section>;
}
