import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
import { useDraftStore, draftMatchesSaved } from "../store/use-draft-store.ts";
import { persistEditingDraft } from "../use-save-draft.ts";
import { StudioTopBar } from "../studio-top-bar.tsx";
import { DraftPersistence } from "../draft-persistence.tsx";
import { RevisionChat } from "../ai-director/revision-chat.tsx";
import { SaveDraftControl } from "../save-draft-control.tsx";
import { savedDraftKey } from "../use-editing.ts";
const project="f93aa0e0-4ada-463c-a7c5-086ddeecd4b9", job="44c3fa22-3ee4-43ec-a476-3e99172c9af2", artifact="b43e8613-09a4-4187-98f1-ad23d5653c09";
const storyboard=JSON.parse(readFileSync(new URL("./published-storyboard.json",import.meta.url)));
const store=()=>useDraftStore.getState();
const originalFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=originalFetch;});
function setup(){
  process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
  useDraftStore.setState({byProject:{},savedByProject:{},restoredByProject:{}});
  store().restore(project,null);
  store().receive(project,{jobId:job,artifactId:artifact},storyboard);
  return new QueryClient({defaultOptions:{queries:{gcTime:Infinity,retry:false}}});
}
function savedFor(draft,revision=1){return {revision,base_job_id:job,base_artifact_id:artifact,window_indices:draft.cuts.map(c=>c.window_index),storyboard,updated_at:"2026-11-04T00:00:00Z"};}
function html(client){Object.assign(useDraftStore.getInitialState(),store());return renderToStaticMarkup(createElement(QueryClientProvider,{client},createElement(SaveDraftControl,{projectId:project,showStatus:true})));}
test("First Cut adoption creates editable cuts and exposes Save Changes",()=>{
  const client=setup();
  assert.equal(store().byProject[project].cuts.length,storyboard.cuts.length);
  assert.equal(draftMatchesSaved(store().byProject[project],null),false);
  assert.match(html(client),/Unsaved changes/);
  assert.match(html(client),/<button[^>]*>Save Changes<\/button>/);
  assert.doesNotMatch(html(client),/disabled/);client.clear();
});
test("one shared save persists exact sequence, synchronizes cache and clears dirty state",async()=>{
  const client=setup();store().move(project,store().byProject[project].cuts[0].id,1);
  const saved=savedFor(store().byProject[project]);let release;
  const response=new Promise(resolve=>{release=resolve;});const requests=[];
  globalThis.fetch=async(url,options)=>{requests.push(JSON.parse(options.body));await response;return Response.json(saved);};
  const first=persistEditingDraft(client,project),second=persistEditingDraft(client,project);
  assert.equal(first,second);
  release();await first;
  assert.equal(requests.length,1);assert.equal(requests[0].expected_revision,0);
  assert.deepEqual(requests[0].window_indices,saved.window_indices);
  assert.deepEqual(client.getQueryData(savedDraftKey(project)),saved);
  assert.equal(draftMatchesSaved(store().byProject[project],store().savedByProject[project]),true);
  assert.match(html(client),/All changes saved/);
  await persistEditingDraft(client,project);assert.equal(requests.length,1);client.clear();
});
test("save failure preserves edits and offers retry; backend conflicts retain expected revision",async()=>{
  const client=setup(),persisted=savedFor(store().byProject[project],7);store().saved(project,persisted);
  store().remove(project,store().byProject[project].cuts[0].id);const edited=store().byProject[project];let expected;
  globalThis.fetch=async(_,options)=>{expected=JSON.parse(options.body).expected_revision;return Response.json({code:"draft_conflict",message:"Changed"},{status:409});};
  await assert.rejects(persistEditingDraft(client,project),e=>e.status===409);
  assert.equal(expected,7);assert.equal(store().byProject[project],edited);assert.equal(store().savedByProject[project],persisted);
  assert.equal(draftMatchesSaved(edited,persisted),false);
  globalThis.fetch=async()=>Response.json(savedFor(edited,8));await persistEditingDraft(client,project);
  assert.equal(draftMatchesSaved(edited,store().savedByProject[project]),true);client.clear();
});
test("edits during save survive the response and need another save",async()=>{
  const client=setup();let release;const response=new Promise(resolve=>{release=resolve;});
  const persisted=savedFor(store().byProject[project]);globalThis.fetch=async()=>{await response;return Response.json(persisted);};
  const saving=persistEditingDraft(client,project);store().remove(project,store().byProject[project].cuts[0].id);
  const edited=store().byProject[project];release();await saving;
  assert.equal(store().byProject[project],edited);assert.equal(draftMatchesSaved(edited,store().savedByProject[project]),false);
  assert.match(html(client),/Unsaved changes/);client.clear();
});
test("refresh and artifact-before-GET restore saved ordering; later cache updates preserve edits",()=>{
  const client=setup();store().move(project,store().byProject[project].cuts[0].id,1);const persisted=savedFor(store().byProject[project],3);
  useDraftStore.setState({byProject:{},savedByProject:{},restoredByProject:{}});
  store().receive(project,{jobId:job,artifactId:artifact},storyboard);store().restore(project,persisted);
  assert.deepEqual(store().byProject[project].cuts.map(c=>c.window_index),persisted.window_indices);
  store().remove(project,store().byProject[project].cuts[0].id);const edited=store().byProject[project];
  store().restore(project,{...persisted,revision:4});assert.equal(store().savedByProject[project].revision,4);assert.equal(store().byProject[project],edited);
  store().restore(project,persisted);assert.equal(store().savedByProject[project].revision,4);client.clear();
});

test("header has status only; Timeline offers navigation and rendering; Director owns one Save",()=>{
  const client=setup();Object.assign(useDraftStore.getInitialState(),store());
  const render=node=>renderToStaticMarkup(createElement(QueryClientProvider,{client},node));
  const header=render(createElement(StudioTopBar,{projectId:project}));
  assert.match(header,/Unsaved changes/);assert.doesNotMatch(header,/>Save Changes<\/button>/);
  const timeline=render(createElement(DraftPersistence,{projectId:project,draft:store().byProject[project]}));
  assert.match(timeline,/Save your draft in AI Director/);assert.match(timeline,/href="#editing-draft-save"/);
  assert.match(timeline,/Make my video/);assert.doesNotMatch(timeline,/>Save Changes<\/button>/);
  const director=render(createElement(RevisionChat,{projectId:project}));
  assert.equal((director.match(/>Save Changes<\/button>/g)??[]).length,1);
  assert.match(director,/entire editing draft, including Timeline edits/);
  store().saved(project,savedFor(store().byProject[project]));Object.assign(useDraftStore.getInitialState(),store());
  const savedDirector=render(createElement(RevisionChat,{projectId:project}));
  assert.match(savedDirector,/<button id="editing-draft-save"[^>]*disabled=""[^>]*>Save Changes<\/button>/);
  client.clear();
});
