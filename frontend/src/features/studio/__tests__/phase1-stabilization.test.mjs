// Phase 1 regression tests: truthful draft/output status, revision request
// separation, preserved previews during renders, and history that never
// presents an old failure as the current state.
import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
import { useDraftStore, draftSyncState } from "../store/use-draft-store.ts";
import { DraftPersistence } from "../draft-persistence.tsx";
import { DraftTimeline } from "../draft-timeline.tsx";
import {
  RevisionChat, pendingRevisionNotices, sendRevisionRequest, useRevisionInstruction, REVISION_NOTICE_COPY,
} from "../ai-director/revision-chat.tsx";
import { DirectorProcessingStatus } from "../ai-director/director-processing-status.tsx";
import { summarizeActivity, buildLifecyclePhases } from "../ai-director/processing-lifecycle.ts";
import { previewMatchesDraft } from "../program-monitor.tsx";
import { usePreviewJob } from "../use-editing.ts";

const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
const job = "44c3fa22-3ee4-43ec-a476-3e99172c9af2", artifact = "b43e8613-09a4-4187-98f1-ad23d5653c09";
const storyboard = JSON.parse(readFileSync(new URL("./published-storyboard.json", import.meta.url)));
const store = () => useDraftStore.getState();
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const uuid = n => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;
const at = minute => `2026-11-04T00:${String(minute).padStart(2, "0")}:00Z`;

function fresh() {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";
  useDraftStore.setState({ byProject: {}, savedByProject: {}, restoredByProject: {}, previewByProject: {} });
  useRevisionInstruction.setState({ byScope: {}, unconfirmedByScope: {} });
  store().restore(project, null);
  store().receive(project, { jobId: job, artifactId: artifact }, storyboard);
  return new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
}
const savedFor = (draft, revision = 1) => ({ revision, base_job_id: job, base_artifact_id: artifact,
  window_indices: draft.cuts.map(c => c.window_index), storyboard, updated_at: "2026-11-04T00:00:00Z" });
function render(client, node) {
  Object.assign(useDraftStore.getInitialState(), store());
  Object.assign(useRevisionInstruction.getInitialState(), useRevisionInstruction.getState());
  return renderToStaticMarkup(createElement(QueryClientProvider, { client }, node));
}
const proposal = (overrides = {}) => ({ id: uuid(5), draft_id: project, base_revision: 1, base_job_id: job, base_artifact_id: artifact,
  instruction: "Move the last moment first", state: "pending", job_status: "succeeded", error_code: null,
  before: [0, 1], after: [1, 0], explanation: "", reasons: [], changes: { removed: [], reordered: true },
  applied_revision: null, progress: null, created_at: at(4), finished_at: at(5), ...overrides });

// ---------------------------------------------------------------- status truth
test("freshly generated cut: timeline says 'No edits yet', not unsaved, and offers no identical render", () => {
  const client = fresh();
  client.setQueryData(["projects", project, "edit-renders"], []);
  client.setQueryData(["projects", project, "revision-proposals"], []);
  const html = render(client, createElement(DraftPersistence, { projectId: project, draft: store().byProject[project] }));
  assert.match(html, /No edits yet · Your current video already uses this order/);
  assert.doesNotMatch(html, /unsaved changes|Save your draft in Rework your story/i);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Make my video<\/button>/);
  client.clear();
});

test("the First Cut timeline summary also reports a fresh cut as 'No edits yet'", () => {
  const client = fresh();
  client.setQueryData(["projects", project, "edit-renders"], []);
  client.setQueryData(["projects", project, "revision-proposals"], []);
  const html = render(client, createElement(DraftTimeline, { projectId: project, draft: store().byProject[project] }));
  assert.match(html, /class="studio-storyboardSummary"[^>]*>[^<]*No edits yet/);
  assert.doesNotMatch(html, /Unsaved changes|unsaved changes/);
  store().move(project, store().byProject[project].cuts[0].id, 1);
  assert.match(render(client, createElement(DraftTimeline, { projectId: project, draft: store().byProject[project] })), /Unsaved changes/);
  client.clear();
});

test("a saved order identical to the generated one says a new video would look the same", () => {
  const client = fresh();
  store().saved(project, savedFor(store().byProject[project], 1));
  client.setQueryData(["projects", project, "edit-renders"], []);
  client.setQueryData(["projects", project, "revision-proposals"], []);
  const html = render(client, createElement(DraftPersistence, { projectId: project, draft: store().byProject[project] }));
  assert.match(html, /Saved as version 1/);
  assert.match(html, /same order as your original video/);
  client.clear();
});

test("monitor notice only claims a match when the shown video really has the current order", () => {
  assert.equal(previewMatchesDraft("none", false, undefined, undefined), null);
  assert.equal(previewMatchesDraft("original", false, undefined, undefined), true);
  assert.equal(previewMatchesDraft("unsaved", true, undefined, undefined), false);
  assert.equal(previewMatchesDraft("saved", false, 1, undefined), true);
  assert.equal(previewMatchesDraft("saved", true, 2, undefined), false);
  assert.equal(previewMatchesDraft("saved", true, 2, { revision: 2, status: "succeeded" }), true);
  assert.equal(previewMatchesDraft("saved", true, 3, { revision: 2, status: "succeeded" }), false);
  assert.equal(previewMatchesDraft("unsaved", true, 2, { revision: 2, status: "succeeded" }), false);
});

// ------------------------------------------------------ revision interaction
test("typed but unsent instruction is flagged in Rework and next to Make my video", () => {
  const client = fresh();
  client.setQueryData(["projects", project, "edit-renders"], []);
  client.setQueryData(["projects", project, "revision-proposals"], []);
  useRevisionInstruction.setState({ byScope: { [project]: "Open with the beach shot" } });
  const rework = render(client, createElement(RevisionChat, { projectId: project }));
  assert.match(rework, /Not sent yet/);
  assert.match(rework, /Based on your original order/);
  // Original baseline can be revised directly: submit is enabled.
  assert.doesNotMatch(rework, /<button type="submit"[^>]*disabled=""/);
  const timeline = render(client, createElement(DraftPersistence, { projectId: project, draft: store().byProject[project] }));
  assert.match(timeline, new RegExp(REVISION_NOTICE_COPY.unsent.slice(0, 40)));
  useRevisionInstruction.setState({ byScope: { [project]: "   " } });
  assert.doesNotMatch(render(client, createElement(RevisionChat, { projectId: project })), /Not sent yet/);
  client.clear();
});

test("a send with an unknown outcome is never reported as 'not sent'", () => {
  const client = fresh();
  client.setQueryData(["projects", project, "edit-renders"], []);
  client.setQueryData(["projects", project, "revision-proposals"], []);
  useRevisionInstruction.setState({ byScope: { [project]: "Open with the beach shot" }, unconfirmedByScope: { [project]: true } });
  assert.deepEqual(pendingRevisionNotices("Open with the beach shot", [], true), ["unconfirmed"]);
  const rework = render(client, createElement(RevisionChat, { projectId: project }));
  assert.doesNotMatch(rework, /Not sent yet/);
  assert.match(rework, /couldn’t confirm whether this was sent/);
  const timeline = render(client, createElement(DraftPersistence, { projectId: project, draft: store().byProject[project] }));
  assert.match(timeline, /couldn’t confirm whether your last change request reached/);
  assert.doesNotMatch(timeline, /hasn’t been sent/);
  client.clear();
});

test("pending revision states are distinguished: in progress, awaiting decision, unsent", () => {
  assert.deepEqual(pendingRevisionNotices("", []), []);
  assert.deepEqual(pendingRevisionNotices("x", []), ["unsent"]);
  assert.deepEqual(pendingRevisionNotices("", [proposal({ job_status: "running", after: null })]), ["in_progress"]);
  assert.deepEqual(pendingRevisionNotices("", [proposal()]), ["awaiting_decision"]);
  // Terminal requests never warn: accepted is already in the saved order, the rest changed nothing.
  for (const state of ["accepted", "rejected", "failed", "stale"]) assert.deepEqual(pendingRevisionNotices("", [proposal({ state })]), []);
});

test("asking from the original cut persists the unchanged base once, then sends one idempotent request", async () => {
  const client = fresh();
  const requests = [];
  const persisted = savedFor(store().byProject[project], 1);
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url: String(url), method: options.method ?? "GET", body: options.body ? JSON.parse(options.body) : null });
    return options.method === "PUT" ? Response.json(persisted) : Response.json({ id: uuid(7) });
  };
  const remembered = { current: null };
  const id = await sendRevisionRequest(client, project, "first_cut", "  Move the last moment first ", remembered);
  assert.equal(id, uuid(7));
  assert.deepEqual(requests.map(r => r.method), ["PUT", "POST"]);
  assert.equal(requests[0].body.expected_revision, 0);
  assert.deepEqual(requests[0].body.window_indices, storyboard.cuts.map(c => c.window_index));
  assert.equal(requests[1].body.draft_revision, 1);
  assert.equal(requests[1].body.instruction, "Move the last moment first");
  assert.equal(draftSyncState(store().byProject[project], store().savedByProject[project]), "saved");
  // A manual retry after a lost response reuses the remembered body (no new request id, no second save).
  globalThis.fetch = async (url, options = {}) => { requests.push({ method: options.method ?? "GET", body: options.body ? JSON.parse(options.body) : null }); throw new TypeError("network"); };
  const firstId = remembered.current.request_id;
  await assert.rejects(sendRevisionRequest(client, project, "first_cut", "Move the last moment first", remembered));
  assert.equal(requests.at(-1).method, "POST");
  assert.equal(requests.at(-1).body.request_id, firstId);
  assert.equal(requests.filter(r => r.method === "PUT").length, 1);
  client.clear();
});

test("unsaved local edits are never silently saved by a revision request", async () => {
  const client = fresh();
  store().move(project, store().byProject[project].cuts[0].id, 1);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({}); };
  await assert.rejects(sendRevisionRequest(client, project, "first_cut", "anything", { current: null }), /Save the draft/);
  assert.equal(calls, 0);
  client.clear();
});

// ----------------------------------------------- output status vs history
const first = uuid(2);
const jobRecord = (id, minute, status = "succeeded") => ({ id, status, created_at: at(minute), started_at: at(minute + 1),
  finished_at: status === "succeeded" || status === "failed" ? at(minute + 2) : null, updated_at: at(minute + 2), attempt_count: 1, error_code: null, progress: null });
function activity({ versions = [], proposals = [], jobs = [], workflow } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  client.setQueryData(["projects", project, "edit-renders"], versions);
  client.setQueryData(["projects", project, "revision-proposals"], proposals);
  client.setQueryData(["projects", project, "ai-jobs", first], jobRecord(first, 0));
  client.setQueryData(["projects", project, "ai-jobs", first, "artifacts"], { items: [] });
  for (const value of jobs) client.setQueryData(["projects", project, "ai-jobs", value.id], value);
  try { return renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(DirectorProcessingStatus, { projectId: project, firstCutJobId: first, workflow }))); }
  finally { client.clear(); }
}

test("a failed revision after a ready video never headlines as the project's latest state", () => {
  const html = activity({ proposals: [proposal({ state: "failed", job_status: "failed", after: null, error_code: "unsupported_revision" })] });
  assert.match(html, /Current video/);
  assert.match(html, /<h3>First Cut · Your video is ready<\/h3>/);
  assert.match(html, /Revision 1 didn’t work · Your draft and video are unchanged/);
  assert.doesNotMatch(html, /<h3>Revision 1 · Revision failed<\/h3>/);
  assert.doesNotMatch(html, /Latest update<\/span>/);
});

test("an in-progress render leads; an older failed revision is history, muted and labelled Earlier", () => {
  const render = { job_id: uuid(6), revision: 1, status: "running" };
  const html = activity({ versions: [render], jobs: [jobRecord(uuid(6), 10, "running")],
    proposals: [proposal({ state: "failed", job_status: "failed", after: null })] });
  assert.match(html, /In progress<\/span><h3>Version 1 Render · Rendering video<\/h3>/);
  const failed = [...html.matchAll(/<li [^>]*data-phase="([^"]+)"[^>]*data-state="failed"[^>]*>/g)];
  assert.ok(failed.length > 0);
  for (const match of failed) assert.match(match[0], /data-historical="true"/);
  assert.match(html, /Revision 1<span class="processing-earlier"> · Earlier<\/span>/);
});

test("a newer failed render keeps the previous ready version as the current video", () => {
  const versions = [{ job_id: uuid(8), revision: 3, status: "failed" }, { job_id: uuid(6), revision: 2, status: "succeeded" }];
  const phases = buildLifecyclePhases(versions, [], new Map([[uuid(6), jobRecord(uuid(6), 10)], [uuid(8), jobRecord(uuid(8), 20, "failed")]]));
  const summary = summarizeActivity(phases, new Set(versions.map(v => v.job_id)), { label: "First Cut", ready: true });
  assert.equal(summary.overline, "Current video");
  assert.equal(summary.title, "Version 2 Render · Your video is ready");
  assert.match(summary.note, /Version 3 couldn’t be made · Version 2 is still ready to watch/);
  // Without any ready output, the honest fallback is the latest update.
  const none = summarizeActivity(phases.slice(1), new Set([uuid(8)]), { label: "First Cut", ready: false });
  assert.equal(none.overline, "Latest update");
});

// ----------------------------------------------------- preview preservation
function previewOf(client) {
  let value;
  function Probe() { value = usePreviewJob(project); return null; }
  render(client, createElement(Probe));
  return value;
}
test("a queued or running render never replaces the playable video on the monitor", () => {
  const client = fresh();
  client.setQueryData(["projects", project, "edit-renders"], [{ job_id: uuid(6), revision: 2, status: "running" }]);
  assert.equal(previewOf(client).jobId, job, "generated cut stays on screen before any version is ready");
  client.setQueryData(["projects", project, "edit-renders"], [{ job_id: uuid(8), revision: 3, status: "queued" }, { job_id: uuid(6), revision: 2, status: "succeeded" }]);
  assert.equal(previewOf(client).jobId, uuid(6), "newest ready version stays on screen while v3 renders");
  client.setQueryData(["projects", project, "edit-renders"], [{ job_id: uuid(8), revision: 3, status: "succeeded" }, { job_id: uuid(6), revision: 2, status: "succeeded" }]);
  assert.equal(previewOf(client).jobId, uuid(8), "switches once the new version is ready");
  // An explicit choice is respected; clearing it returns to automatic selection.
  store().setPreview(project, uuid(6));
  assert.equal(previewOf(client).jobId, uuid(6));
  store().clearPreviewSelection(project);
  assert.equal(store().previewByProject[project], undefined);
  assert.equal(previewOf(client).jobId, uuid(8));
  client.clear();
});
