import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
const { ConnectedDirector } = require("../ai-director/connected-director.tsx");
const { recoveryJob, validFirstCutRequest, saveFirstCutRequest, readFirstCutRequest } = require("../ai-director/first-cut-recovery.ts");
const { useEditorStore } = require("../store/use-editor-store.ts");
const { useDraftStore } = require("../store/use-draft-store.ts");
const { parseJobProgress } = require("../../../lib/api/job-progress.ts");
const project = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";
const oldId = "33333333-3333-4333-8333-333333333333";
const artifactId = "44444444-4444-4444-8444-444444444444";
const mediaId = "55555555-5555-4555-8555-555555555555";
const stamp = "2026-01-01T00:00:00Z";
const storyboard = {target_seconds:30,total_seconds:5,cuts:[{window_index:0,start_seconds:0,end_seconds:5}]};
const brief = {kind:"first_cut",intent:"A cinematic journey",target_seconds:45,media_ids:[mediaId]};
const originalFetch = globalThis.fetch;
// renderToStaticMarkup uses zustand's server snapshot (getInitialState), so each
// render seeds both the live store and its initial snapshot, then cleans both.
function resetStores() {
  useEditorStore.setState({activeJobByProject:{},selectedMediaByProject:{}});
  for (const key of Object.keys(useEditorStore.getInitialState().activeJobByProject)) delete useEditorStore.getInitialState().activeJobByProject[key];
  const initialSelection = useEditorStore.getInitialState().selectedMediaByProject ?? {};
  for (const key of Object.keys(initialSelection)) delete initialSelection[key];
  useDraftStore.setState({byProject:{},savedByProject:{},restoredByProject:{}});
  for (const key of Object.keys(useDraftStore.getInitialState().byProject)) delete useDraftStore.getInitialState().byProject[key];
  for (const key of Object.keys(useDraftStore.getInitialState().savedByProject)) delete useDraftStore.getInitialState().savedByProject[key];
  for (const key of Object.keys(useDraftStore.getInitialState().restoredByProject)) delete useDraftStore.getInitialState().restoredByProject[key];
}
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
  resetStores();
});

function render({status, previousSuccess = false, video = true, story = true, editable = true, retry = false} = {}) {
  globalThis.fetch = () => { throw new Error("No network or inference permitted in frontend tests"); };
  resetStores();
  const client = new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity}}});
  const key = (...parts) => ["projects",project,...parts];
  const job = status ? {id:jobId,status,error_code:"SECRET_PROVIDER_EXCEPTION"} : null;
  client.setQueryData(key("ai-jobs","recoverable-list"),job ? [job] : []);
  // Retry availability needs the original request inputs plus surviving media.
  client.setQueryData(key("media"),retry ? [{id:mediaId}] : []);
  client.setQueryData(key("edit-draft"),null);
  if (job) {
    useEditorStore.getState().setActiveJob(project,jobId);
    useEditorStore.getInitialState().activeJobByProject[project] = jobId;
    client.setQueryData(key("ai-jobs",jobId),job);
    if (retry) client.setQueryData(key("first-cut-inputs",jobId),brief);
  }
  if (status === "succeeded" || previousSuccess) {
    const base = previousSuccess ? oldId : jobId;
    client.setQueryData(key("ai-jobs",base),{id:base,status:"succeeded"});
    client.setQueryData(key("ai-jobs",base,"artifacts"),{items:[
      ...(story ? [{id:artifactId,kind:"storyboard",size_bytes:100}] : []),
      ...(video ? [{id:mediaId,kind:"video",size_bytes:1024}] : []),
    ]});
    client.setQueryData(key("ai-jobs",base,"artifacts",artifactId,"public-storyboard"),storyboard);
    if (editable) {
      useDraftStore.getState().receive(project,{jobId:base,artifactId},storyboard);
      useDraftStore.getInitialState().byProject[project] = useDraftStore.getState().byProject[project];
    }
    client.setQueryData(key("revision-proposals"),[]);
  }
  const html = renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(ConnectedDirector,{projectId:project})));
  client.clear();
  return html;
}

for (const status of [undefined,"queued","running","failed"]) {
  test(`Rework is absent for initial generation state ${status ?? "empty"}`, () => {
    const html = render({status});
    assert.doesNotMatch(html,/Rework your story|revision-instruction|SECRET_PROVIDER_EXCEPTION/);
    assert.match(html,/Create Your First Cut/);
  });
}
test("Rework requires successful job, video, storyboard, and editable draft", () => {
  assert.match(render({status:"succeeded"}),/Rework your story/);
  for (const options of [{video:false},{story:false},{editable:false}]) {
    assert.doesNotMatch(render({status:"succeeded",...options}),/Rework your story/);
  }
});
test("Try again sits immediately below the failure message, ahead of unrelated sections", () => {
  const html = render({status:"failed",retry:true});
  assert.match(html,/Try again/);
  assert.match(html,/Nothing new was started/);
  assert.doesNotMatch(html,/Rework your story|SECRET_PROVIDER_EXCEPTION/);
  const failure = html.indexOf("Nothing new was started");
  const retry = html.indexOf("Try again");
  const timing = html.indexOf("Time so far");
  assert.ok(failure >= 0 && retry > failure,"Try again must follow the failure message");
  assert.ok(timing > retry,"Unrelated timing details must stay below Try again");
});
test("a failure without stored inputs offers editing instead of retry", () => {
  const html = render({status:"failed"});
  assert.match(html,/original story idea or selected footage/);
  assert.match(html,/Edit First Cut/);
  assert.doesNotMatch(html,/Try again/);
});
test("a newer failed, queued, or running job does not remove an earlier editable cut", () => {
  for (const status of ["failed","queued","running"]) {
    assert.match(render({status,previousSuccess:true}),/Rework your story/);
  }
});
test("server recovery includes failed history and prioritizes existing processing", () => {
  const failed = {id:jobId,status:"failed"};
  assert.equal(recoveryJob([failed]).id,jobId);
  assert.equal(recoveryJob([failed,{id:oldId,status:"running"}]).id,oldId);
  assert.equal(recoveryJob([]),undefined);
});
test("retry input snapshots survive refresh, stay job/project scoped, and tolerate missing storage", () => {
  const entries = new Map();
  globalThis.window = {sessionStorage:{getItem:key=>entries.get(key)??null,setItem:(key,value)=>entries.set(key,value)}};
  saveFirstCutRequest(project,jobId,brief);
  assert.deepEqual(readFirstCutRequest(project,jobId),brief);
  assert.equal(readFirstCutRequest(project,oldId),null);
  assert.equal(readFirstCutRequest(oldId,jobId),null);
  entries.set(`intentcut:first-cut-inputs:${project}:${jobId}`,"broken JSON");
  assert.equal(readFirstCutRequest(project,jobId),null);
  delete globalThis.window;
  assert.doesNotThrow(()=>saveFirstCutRequest(project,jobId,brief));
  assert.equal(readFirstCutRequest(project,jobId),null);
});
test("invalid inputs cannot be retried; up to ten distinct media assets are supported", () => {
  assert.equal(validFirstCutRequest(brief),true);
  for (const bad of [{intent:" "},{target_seconds:0},{target_seconds:Infinity},{media_ids:[]},{media_ids:[mediaId,mediaId]},{kind:"revision"}]) {
    assert.equal(validFirstCutRequest({...brief,...bad}),false);
  }
  const media_ids = Array.from({length:10},(_,i)=>`${String(i).padStart(8,"0")}-1111-4111-8111-111111111111`);
  assert.equal(validFirstCutRequest({...brief,media_ids}),true);
  assert.equal(validFirstCutRequest({...brief,media_ids:[...media_ids,mediaId]}),false);
});
test("progress accepts thirty temporal windows and rejects out-of-contract counts", () => {
  const progress = {stage:"understanding_footage",stage_started_at:stamp,updated_at:stamp,completed_windows:30,total_windows:30};
  assert.equal(parseJobProgress(progress).total_windows,30);
  assert.throws(()=>parseJobProgress({...progress,total_windows:31}));
  assert.throws(()=>parseJobProgress({...progress,completed_windows:31}));
});
