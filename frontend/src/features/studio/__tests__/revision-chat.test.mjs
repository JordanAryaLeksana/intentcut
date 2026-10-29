import test, {afterEach} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {createRequire} from "node:module";
const require=createRequire(import.meta.url);
const {QueryClient,QueryClientProvider,QueryObserver}=require("@tanstack/react-query");
import {parseProposal,requestRevision,decideProposal} from "../../../lib/api/revisions.ts";
import {ProposalReview,proposalOptions,proposalStatus} from "../ai-director/revision-chat.tsx";
import {useDraftStore,draftMatchesSaved} from "../store/use-draft-store.ts";
const project="f93aa0e0-4ada-463c-a7c5-086ddeecd4b9",id="11111111-1111-4111-8111-111111111111";
const job="44c3fa22-3ee4-43ec-a476-3e99172c9af2",artifact="b43e8613-09a4-4187-98f1-ad23d5653c09";
const storyboard=JSON.parse(readFileSync(new URL("./published-storyboard.json",import.meta.url)));
const saved={revision:1,base_job_id:job,base_artifact_id:artifact,window_indices:[2,6,4,8,5],storyboard,updated_at:"2026-10-30T00:00:00Z"};
const proposal={id,draft_id:project,base_revision:1,base_job_id:job,base_artifact_id:artifact,instruction:"Move the last cut first",state:"pending",job_status:"succeeded",error_code:null,before:[2,6,4,8,5],after:[5,2,6,4],explanation:"Lead with the creator’s selected cut.",reasons:[5,2,6,4].map(window_index=>({window_index,reason:"Requested position"})),changes:{removed:[8],reordered:true},applied_revision:null,progress:null};
const originalFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=originalFetch;});
function reset(){useDraftStore.setState({byProject:{},savedByProject:{},restoredByProject:{}});useDraftStore.getState().restore(project,saved);}

test("review shows actual instruction, before/after sequence and explicit decisions",()=>{
 const c=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity}}});
 const html=renderToStaticMarkup(createElement(QueryClientProvider,{client:c},createElement(ProposalReview,{projectId:project,proposal})));
 assert.match(html,/Move the last cut first/);assert.match(html,/Current at request/);assert.match(html,/Proposed order/);
 assert.match(html,/Accept proposal/);assert.match(html,/Reject proposal/);assert.match(html,/approval is required/);
 assert.doesNotMatch(html,/MP4 updated|rendered successfully|<script/);c.clear();
});
test("queued/running/failed/stale states never imply an applied edit",()=>{
 assert.match(proposalStatus({...proposal,job_status:"queued"}),/Waiting/);
 assert.match(proposalStatus({...proposal,job_status:"running",progress:{stage:"revising_sequence"}}),/Muse/);
 assert.match(proposalStatus({...proposal,state:"failed",error_code:"unsupported_revision"}),/Unsupported/);
 assert.match(proposalStatus({...proposal,state:"stale"}),/Stale/);
 assert.match(proposalStatus({...proposal,state:"accepted",applied_revision:2}),/Not rendered/);
});
test("acceptance applies a saved revision as one undoable edit",()=>{reset();
 const store=useDraftStore.getState();const current=store.byProject[project];
 store.select(project,current.cuts[0].id);
 store.applyAccepted(project,{...saved,revision:2,window_indices:proposal.after},current.revision);
 assert.deepEqual(useDraftStore.getState().byProject[project].cuts.map(c=>c.window_index),proposal.after);
 assert.equal(draftMatchesSaved(useDraftStore.getState().byProject[project],useDraftStore.getState().savedByProject[project]),true);
 store.undo(project);
 assert.deepEqual(useDraftStore.getState().byProject[project].cuts.map(c=>c.window_index),saved.window_indices);
 assert.equal(draftMatchesSaved(useDraftStore.getState().byProject[project],useDraftStore.getState().savedByProject[project]),false);
 store.redo(project);assert.deepEqual(useDraftStore.getState().byProject[project].cuts.map(c=>c.window_index),proposal.after);
});
test("late acceptance does not erase newer local edits or another project",()=>{reset();
 const store=useDraftStore.getState(),current=store.byProject[project];
 store.restore("other",saved);
 const other=useDraftStore.getState().byProject.other;
 store.remove(project,current.cuts[0].id);
 const edited=useDraftStore.getState().byProject[project];
 store.applyAccepted(project,{...saved,revision:2,window_indices:proposal.after},current.revision);
 assert.equal(useDraftStore.getState().byProject[project],edited);
 assert.equal(useDraftStore.getState().byProject.other,other);
 assert.equal(draftMatchesSaved(edited,useDraftStore.getState().savedByProject[project]),false);
});
test("refresh recovers persisted proposals using GET and terminal polling stops",async()=>{
 process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
 const requests=[];globalThis.fetch=async(url,options)=>{requests.push({url,method:options.method??"GET"});return Response.json({items:[proposal]});};
 const c=new QueryClient({defaultOptions:{queries:{gcTime:Infinity}}});
 const observer=new QueryObserver(c,proposalOptions(project));const unsubscribe=observer.subscribe(()=>{});
 const result=await observer.refetch();assert.equal(result.data[0].id,id);
 assert.equal(proposalOptions(project).refetchInterval({state:{data:[proposal],error:null}}),false);
 assert.equal(proposalOptions(project).refetchInterval({state:{data:[{...proposal,job_status:"running"}],error:null}}),2000);
 assert.ok(requests.every(r=>r.method==="GET"));unsubscribe();c.clear();
});
test("project and fabricated sequence responses are rejected",()=>{
 assert.throws(()=>parseProposal({...proposal,draft_id:id},project));
 assert.throws(()=>parseProposal({...proposal,after:[999]},project));
 assert.throws(()=>parseProposal({...proposal,after:[2,2]},project));
});
test("submit and accept send exact revision with no automatic retries",async()=>{
 process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";const requests=[];
 globalThis.fetch=async(url,options)=>{requests.push({url,...options});return Response.json(requests.length===1?{id}:{proposal:{...proposal,state:"accepted",applied_revision:2},draft:{...saved,revision:2,window_indices:proposal.after}});};
 await requestRevision(project,{request_id:id,draft_revision:1,instruction:proposal.instruction});
 const result=await decideProposal(project,id,1);assert.equal(result.draft.revision,2);
 assert.deepEqual(JSON.parse(requests[1].body),{expected_revision:1});
 assert.equal(requests.length,2);assert.ok(requests.every(r=>r.method==="POST"));
});
