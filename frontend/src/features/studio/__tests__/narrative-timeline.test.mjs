import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";
// TSX loads the app's TS modules as CommonJS in this package. Use the same
// React Query entry point so the provider and hooks share one context.
const require = createRequire(import.meta.url);
const { QueryClient, QueryClientProvider, QueryObserver } = require("@tanstack/react-query");
import { JobTimeline, NarrativeTimeline } from "../narrative-timeline.tsx";
import { useEditorStore } from "../store/use-editor-store.ts";
import { readSavedJobId } from "../store/job-recovery.ts";
import { aiJobKey, aiJobStatusOptions, jobPollingInterval } from "../ai-director/hooks/use-ai-job-status.ts";
import { aiArtifactsKey } from "../ai-director/hooks/use-ai-artifacts.ts";
import { publicStoryboardOptions } from "../ai-director/hooks/use-public-storyboard.ts";
import { parsePublicStoryboard } from "../ai-director/storyboard/storyboard-schema.ts";

const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
const job = "44c3fa22-3ee4-43ec-a476-3e99172c9af2";
const artifact = "b43e8613-09a4-4187-98f1-ad23d5653c09";
const other = "11111111-1111-4111-8111-111111111111";
const fixture = JSON.parse(readFileSync(new URL("./published-storyboard.json", import.meta.url)));
const originalFetch = globalThis.fetch;
const clients = [];
function client() {
  const result = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, gcTime: Infinity } } });
  clients.push(result);
  return result;
}
afterEach(() => {
  clients.forEach((c) => c.clear()); clients.length = 0;
  globalThis.fetch = originalFetch;
  useEditorStore.setState({ activeJobByProject: {} });
});
function render(c, id = project) {
  // The job subtree is rendered with explicit identifiers: SSR intentionally uses
  // Zustand's empty initial snapshot. Browser checks cover selection and recovery.
  const selected = useEditorStore.getState().activeJobByProject[id];
  const component = selected
    ? createElement(JobTimeline, { projectId: id, jobId: selected })
    : createElement(NarrativeTimeline, { projectId: id });
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: c }, component));
}
function seed(c, status = "succeeded") {
  useEditorStore.setState({ activeJobByProject: { [project]: job } });
  c.setQueryData(aiJobKey(project, job), { status });
}
function seedArtifacts(c, items = [{ id: artifact, kind: "storyboard" }]) {
  c.setQueryData(aiArtifactsKey(project, job), { items });
}
function error(c, queryKey) {
  c.getQueryCache().build(c, { queryKey }).setState({ status: "error", error: new Error("Unavailable"), fetchStatus: "idle" });
}

test("five real cuts render automatically in published array order with source durations", () => {
  const c = client(); seed(c); seedArtifacts(c);
  c.setQueryData(publicStoryboardOptions(project, job, artifact, true).queryKey, parsePublicStoryboard(fixture));
  const html = render(c);
  assert.match(html, /5 scenes/);
  assert.match(html, /Planned cuts 18.82s/);
  assert.equal((html.match(/class="studio-cut"/g) ?? []).length, 5);
  const ranges = ["10.00s – 13.74s", "0.00s – 5.00s", "5.00s – 10.00s", "10.00s – 11.05s", "10.00s – 14.04s"];
  let position = -1;
  for (const range of ranges) { const next = html.indexOf(range); assert.ok(next > position); position = next; }
  assert.match(html, /3.74s/); assert.match(html, /1.05s/); assert.match(html, /4.04s/);
  assert.match(html, new RegExp(fixture.cuts[0].media_id));
  assert.doesNotMatch(html, /View storyboard|editorial_reason|draggable/);
});

test("no-job, queued, running, failed and loading states are distinct", () => {
  const c = client();
  assert.match(render(c), /Restoring saved draft/);
  useEditorStore.setState({ activeJobByProject: { [project]: job } });
  assert.match(render(c), /Loading job status/);
  for (const [status, label] of [["queued", "First cut queued"], ["running", "First cut processing"], ["failed", "First cut failed"]]) {
    seed(c, status); assert.match(render(c), new RegExp(label)); assert.doesNotMatch(render(c), /class="studio-cut"/);
  }
  seed(c); assert.match(render(c), /Loading storyboard/);
  seedArtifacts(c); assert.match(render(c), /Retrieving published cuts/);
});

test("missing artifact and retrieval/parse errors offer retry without stale cuts", () => {
  const c = client(); seed(c); seedArtifacts(c, []);
  assert.match(render(c), /No storyboard artifact available/);
  assert.match(render(c), /Retry retrieval/);
  error(c, aiArtifactsKey(project, job)); assert.match(render(c), /Could not retrieve artifacts/);
  seedArtifacts(c); error(c, publicStoryboardOptions(project, job, artifact, true).queryKey);
  assert.match(render(c), /Could not load storyboard/);
  c.removeQueries({ queryKey: aiJobKey(project, job) });
  error(c, aiJobKey(project, job)); assert.match(render(c), /Could not retrieve job status/);
  assert.doesNotMatch(render(c), /class="studio-cut"/);
});

test("project and job changes never reuse previous cuts", () => {
  const c = client(); seed(c); seedArtifacts(c);
  c.setQueryData(publicStoryboardOptions(project, job, artifact, true).queryKey, fixture);
  assert.match(render(c), /5 scenes/);
  assert.doesNotMatch(render(c, other), /5 scenes|class="studio-cut"/);
  useEditorStore.getState().setActiveJob(project, other);
  assert.match(render(c), /Loading job status/);
  assert.doesNotMatch(render(c), /5 scenes|class="studio-cut"/);
  assert.notDeepEqual(publicStoryboardOptions(other, job, artifact, true).queryKey, publicStoryboardOptions(project, job, artifact, true).queryKey);
  assert.notDeepEqual(publicStoryboardOptions(project, other, artifact, true).queryKey, publicStoryboardOptions(project, job, artifact, true).queryKey);
});

test("automatic storyboard observer and error retry only GET the existing artifact", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";
  const c = client(); const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, method: options.method ?? "GET" });
    return Response.json(requests.length === 1 ? { invalid: true } : fixture);
  };
  const observer = new QueryObserver(c, publicStoryboardOptions(project, job, artifact, true));
  let unsubscribe;
  const failed = new Promise((resolve) => { unsubscribe = observer.subscribe((result) => { if (result.isError) resolve(); }); });
  await failed;
  const result = await observer.refetch();
  assert.equal(result.data.cuts.length, 5);
  assert.deepEqual(requests.map((r) => r.method), ["GET", "GET"]);
  assert.ok(requests.every((r) => r.url.endsWith(`/ai-jobs/${job}/artifacts/${artifact}`)));
  unsubscribe();
});

test("terminal status and deleted jobs stop polling while queued/running continue", () => {
  for (const status of ["succeeded", "failed"]) assert.equal(jobPollingInterval(status), false);
  for (const status of ["queued", "running"]) assert.equal(jobPollingInterval(status), 2000);
  assert.equal(jobPollingInterval(undefined, new Error("404")), false);
  const options = aiJobStatusOptions(project, job);
  assert.equal(options.retry, false); assert.equal(options.retryOnMount, false);
  assert.equal(options.refetchInterval({ state: { data: { status: "succeeded" }, error: null } }), false);
  assert.equal(options.refetchInterval({ state: { error: new Error("404") } }), false);
});

test("session recovery validates IDs, isolates projects and tolerates unavailable storage", () => {
  const storage = { getItem: (key) => key === `intentcut:ai-job:${project}` ? job : null };
  assert.equal(readSavedJobId(project, storage), job);
  assert.equal(readSavedJobId(other, storage), null);
  for (const invalid of ["", "invalid", "../../job", null]) assert.equal(readSavedJobId(project, { getItem: () => invalid }), null);
  assert.equal(readSavedJobId(project, { getItem: () => { throw Error("Blocked"); } }), null);
});

test("real fractional source totals validate without treating render duration as source total", () => {
  const parsed = parsePublicStoryboard(fixture);
  assert.equal(parsed.total_seconds, 18.823334);
  assert.ok(parsed.render_seconds > parsed.total_seconds);
  assert.deepEqual(parsed.cuts.map((cut) => cut.window_index), [2, 6, 4, 8, 5]);
  assert.throws(() => parsePublicStoryboard({ ...fixture, total_seconds: fixture.render_seconds }));
});


test("published cuts stay readable when a terminal job focus-refresh fails", () => {
  const c = client(); seed(c); seedArtifacts(c);
  c.setQueryData(publicStoryboardOptions(project, job, artifact, true).queryKey, fixture);
  error(c, aiJobKey(project, job));
  assert.match(render(c), /5 scenes/);
  assert.doesNotMatch(render(c), /Could not retrieve job status/);
});
