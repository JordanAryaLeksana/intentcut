import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";
import { ProcessingTimeline } from "../ai-director/processing-timeline.tsx";
import { observeJob, elapsedSeconds, STAGE_COPY } from "../ai-director/processing-state.ts";
import { aiJobKey, aiJobStatusOptions, jobPollingInterval } from "../ai-director/hooks/use-ai-job-status.ts";
import { getAIJob } from "../../../lib/api/ai-jobs.ts";
import { parseJobProgress } from "../../../lib/api/job-progress.ts";
import { ApiError } from "../../../lib/api/transport.ts";
const require = createRequire(import.meta.url);
const { QueryClient, QueryObserver, focusManager } = require("@tanstack/react-query");

const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
const id = "44c3fa22-3ee4-43ec-a476-3e99172c9af2";
const other = "11111111-1111-4111-8111-111111111111";
const at = (minute) => `2026-10-29T10:${String(minute).padStart(2, "0")}:00Z`;
const queued = { id, status:"queued", created_at:at(0), updated_at:at(0), started_at:null, finished_at:null, attempt_count:0, error_code:null };
const progress = (stage, counts = {}) => ({ stage, stage_started_at:at(2), updated_at:at(3), ...counts });
const running = (stage = "preparing_media", counts = {}) => ({ ...queued, status:"running", started_at:at(1), attempt_count:1, progress:progress(stage, counts) });
const render = (job, now = Date.parse(at(5)), unconfirmed = false) => renderToStaticMarkup(createElement(ProcessingTimeline, { job, now, unconfirmed }));
const oldFetch = globalThis.fetch;
const clients = [];
afterEach(() => { globalThis.fetch=oldFetch;clients.forEach(c=>{c.unmount();c.clear();});clients.length=0;focusManager.setFocused(undefined); });
function client() { const c = new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity}}});clients.push(c);return c; }
const settle = () => new Promise(resolve=>setTimeout(resolve,10));

test("queued acceptance is separate from active processing and has no invented counts", () => {
  const html=render(queued);
  assert.match(html,/Request accepted/);assert.match(html,/Accepted · waiting/);
  assert.match(html,/Processing has not started/);assert.match(html,/5:00/);
  assert.doesNotMatch(html,/aria-current|windows validated|\d+%|\bETA\b|offline|estimated/i);
});

test("running displays only the actual active stage without inventing completed stage history", () => {
  for (const stage of Object.keys(STAGE_COPY)) {
    const html=render(running(stage));
    assert.ok(html.includes(STAGE_COPY[stage].title));
    assert.match(html,/aria-current="step"/);
    assert.equal((html.match(/data-state="complete"/g)||[]).length,1); // acceptance only
    assert.doesNotMatch(html,/\d+%|ETA|estimated|Remaining/);
  }
  assert.doesNotMatch(render(running("rendering_video")),/Understanding footage|Selecting the story/);
});

test("window counts come from the backend, including zero completed", () => {
  for (const completed of [0,1,2]) {
    assert.match(render(running("understanding_footage",{completed_windows:completed,total_windows:2})),new RegExp(`${completed} of 2 windows validated`));
  }
  assert.doesNotMatch(render({...running(),progress:null}),/windows validated/);
});

test("elapsed time includes queue wait and does not reset with stage changes", () => {
  assert.equal(elapsedSeconds(running("understanding_footage"),Date.parse(at(5))),300);
  assert.equal(elapsedSeconds(running("rendering_video"),Date.parse(at(5))),300);
  assert.equal(elapsedSeconds(running("rendering_video"),Date.parse(at(6))),360);
  assert.equal(elapsedSeconds({...queued,status:"succeeded",finished_at:at(8)},Date.parse(at(20))),480);
  assert.equal(elapsedSeconds({...queued,status:"failed",finished_at:null},Date.parse(at(20))),null);
});

test("historical and expired-stage snapshots do not fabricate activity", () => {
  const html=render({...running(),progress:undefined});
  assert.match(html,/Current stage unavailable/);assert.doesNotMatch(html,/aria-current|Preparing media/);
  const ready=render({...queued,status:"succeeded",finished_at:at(8)});
  assert.match(ready,/First cut ready/);assert.match(ready,/View first cut/);assert.match(ready,/8:00/);
  assert.doesNotMatch(ready,/Preparing media|windows validated/);
});

test("failure retains only same-attempt observations, and not a claimed failure stage", () => {
  const observed=observeJob(undefined,running("rendering_video"));
  const failed=observeJob(observed,{...observed,status:"failed",progress:null,finished_at:at(4),error_code:"private-error-secret"});
  const html=render(failed);
  assert.match(html,/First cut failed/);assert.match(html,/Last reported stage this session: Rendering video/);
  assert.doesNotMatch(html,/private-error-secret|aria-current/);
  assert.equal(observeJob(undefined,{...failed,lastObservedProgress:undefined}).lastObservedProgress,undefined);
  assert.equal(observeJob(observed,{...running(),id:other,progress:null}).lastObservedProgress,undefined);
  assert.equal(observeJob(observed,{...running(),attempt_count:2,progress:null}).lastObservedProgress,undefined);
  assert.equal(observeJob(observed,{...queued,attempt_count:1}).lastObservedProgress,undefined);
  assert.equal(observeJob(observed,{...running(),started_at:at(4),progress:null}).lastObservedProgress,undefined);
});

test("failed refresh does not portray a cached stage as currently active", () => {
  const html=render(running("understanding_footage",{completed_windows:1,total_windows:2}),Date.parse(at(5)),true);
  assert.match(html,/Status check interrupted/);assert.doesNotMatch(html,/aria-current|windows validated/);
});

test("progress parser rejects unknown stages, invalid timestamps and invalid counters", () => {
  for (const invalid of [
    progress("private"),progress("rendering_video",{completed_windows:1,total_windows:2}),
    progress("understanding_footage",{completed_windows:3,total_windows:2}),
    progress("understanding_footage",{completed_windows:true,total_windows:2}),
    progress("understanding_footage",{completed_windows:1}),
    {...progress("preparing_media"),stage_started_at:"bad"},
    {...progress("preparing_media"),updated_at:at(0)},
  ]) assert.throws(()=>parseJobProgress(invalid),ApiError);
  assert.equal(parseJobProgress(undefined),null);
  assert.equal("private" in parseJobProgress({...progress("preparing_media"),private:"secret"}),false);
});

test("GET accepts both historical jobs and validated progress snapshots", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
  globalThis.fetch=async()=>Response.json(queued);
  assert.equal((await getAIJob(project,id)).progress,null);
  globalThis.fetch=async()=>Response.json(running("understanding_footage",{completed_windows:1,total_windows:2}));
  assert.equal((await getAIJob(project,id)).progress.completed_windows,1);
});

test("polling is 2 seconds while active, stops for terminal/404, and refetches on focus", () => {
  assert.equal(jobPollingInterval("queued"),2000);assert.equal(jobPollingInterval("running"),2000);
  assert.equal(jobPollingInterval("succeeded"),false);assert.equal(jobPollingInterval("failed"),false);
  assert.equal(jobPollingInterval("running",new ApiError("missing",404,"not_found")),false);
  assert.equal(jobPollingInterval("running",new ApiError("temporary",503,"database_unavailable")),2000);
  assert.equal(aiJobStatusOptions(project,id).refetchOnWindowFocus,true);
});

test("late responses from a previous job cannot replace the selected job", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
  let release;
  const slow=new Promise(resolve=>{release=resolve;});
  globalThis.fetch=async(url)=>url.endsWith(id)?slow:Response.json({...running("selecting_story"),id:other});
  const c=client();const observer=new QueryObserver(c,aiJobStatusOptions(project,id));
  const unsubscribe=observer.subscribe(()=>{});
  observer.setOptions(aiJobStatusOptions(project,other));
  await observer.refetch();
  release(Response.json(running("preparing_media")));await settle();
  assert.equal(observer.getCurrentResult().data.id,other);
  assert.equal(observer.getCurrentResult().data.progress.stage,"selecting_story");
  unsubscribe();
});

test("project-scoped keys prevent another project's cached job from being shown", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
  const c=client();c.setQueryData(aiJobKey(project,id),running("rendering_video"));
  globalThis.fetch=async()=>Response.json(queued);
  const observer=new QueryObserver(c,aiJobStatusOptions(other,id));
  assert.equal(observer.getCurrentResult().data,undefined);
  const unsubscribe=observer.subscribe(()=>{});await observer.refetch();
  assert.equal(observer.getCurrentResult().data.status,"queued");
  assert.equal(c.getQueryData(aiJobKey(project,id)).progress.stage,"rendering_video");
  unsubscribe();
});

test("focus revalidates an active job through the existing GET query", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8011";
  let requests=0;
  globalThis.fetch=async(_url,options)=>{assert.equal(options.method??"GET","GET");requests++;return Response.json(running("extracting_windows"));};
  const c=client();c.mount();focusManager.setFocused(false);
  const observer=new QueryObserver(c,{...aiJobStatusOptions(project,id),initialData:queued,refetchOnMount:false});
  const unsubscribe=observer.subscribe(()=>{});focusManager.setFocused(true);await settle();
  assert.equal(requests,1);assert.equal(observer.getCurrentResult().data.progress.stage,"extracting_windows");
  unsubscribe();
});
