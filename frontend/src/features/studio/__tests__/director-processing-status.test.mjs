import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { createElement } = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
const { DirectorProcessingStatus } = require("../ai-director/director-processing-status.tsx");
const { buildLifecyclePhases, revisionPhase, renderPhase } = require("../ai-director/processing-lifecycle.ts");
const { parseProposal } = require("../../../lib/api/revisions.ts");
const project = "11111111-1111-4111-8111-111111111111", first = "22222222-2222-4222-8222-222222222222";
const id = n => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;
const at = minute => `2026-11-04T00:${String(minute).padStart(2, "0")}:00Z`;
const job = (id, minute, status = "succeeded") => ({ id, status, created_at: at(minute), started_at: status === "queued" ? null : at(minute + 1), finished_at: status === "succeeded" || status === "failed" ? at(minute + 2) : null, updated_at: at(minute + 2), attempt_count: 1, error_code: null, progress: null });
const proposal = (number, base, minute, state = "accepted", status = "succeeded") => ({ id: id(number), draft_id: project, base_revision: base, base_job_id: first, base_artifact_id: first, instruction: "Move the last moment first", state, job_status: status, error_code: null, before: [0, 1], after: status === "succeeded" ? [1, 0] : null, explanation: "Requested order", reasons: [], changes: { removed: [], reordered: true }, applied_revision: state === "accepted" ? base + 1 : null, progress: null, created_at: at(minute), finished_at: status === "succeeded" ? at(minute + 1) : null });
function render({ versions = [], proposals = [], jobs = [], firstStatus = "succeeded" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  client.setQueryData(["projects", project, "edit-renders"], versions);
  client.setQueryData(["projects", project, "revision-proposals"], proposals);
  client.setQueryData(["projects", project, "ai-jobs", first], job(first, 0, firstStatus));
  client.setQueryData(["projects", project, "ai-jobs", first, "artifacts"], { items: [] });
  for (const value of jobs) client.setQueryData(["projects", project, "ai-jobs", value.id], value);
  try { return renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(DirectorProcessingStatus, { projectId: project, firstCutJobId: first }))); }
  finally { client.clear(); }
}
const versions = [{ job_id: id(6), revision: 3, status: "running" }, { job_id: id(4), revision: 2, status: "succeeded" }];
const proposals = [proposal(5, 2, 12), proposal(3, 1, 4)];
const jobs = [job(id(4), 8), job(id(6), 16, "running")];

test("First Cut alone preserves its original processing timeline and ready state", () => {
  const html = render();
  assert.match(html, /Your first cut is ready/);
  assert.match(html, /Request received/); assert.match(html, /Creating your video/); assert.match(html, /Your video is ready/);
  assert.match(html, /Watch your video/); assert.match(html, /2:00/);
  assert.equal((html.match(/class="processing-milestones"/g) ?? []).length, 1);
  assert.match(render({ firstStatus: "queued" }), /Waiting to start/);
  assert.match(render({ firstStatus: "failed" }), /This try didn’t finish/);
});

test("First Cut, revisions and subsequent renders share a chronological connected list", () => {
  const html = render({ versions, proposals, jobs });
  const labels = [...html.matchAll(/class="processing-phaseLabel">([^<]+)<\/p>/g)].map(match => match[1]);
  assert.deepEqual(labels, ["First Cut", "Revision 1", "Version 2 Render", "Revision 2", "Version 3 Render"]);
  assert.equal((html.match(/class="processing-milestones"/g) ?? []).length, 1);
  assert.doesNotMatch(html, /Revision &amp; render history|<article/);
  assert.match(html, /data-current="true" aria-current="step"/);
  assert.match(html, /role="region" aria-label="Project processing timeline"/);
});

test("polling and refresh rebuild identical history without duplicate events", () => {
  const map = new Map(jobs.map(j => [j.id, j]));
  const expected = buildLifecyclePhases(versions, proposals, map);
  assert.deepEqual(buildLifecyclePhases([...versions, versions[0]], [...proposals, proposals[0]], map), expected);
  assert.deepEqual(buildLifecyclePhases(structuredClone(versions), structuredClone(proposals), new Map(structuredClone(jobs).map(j => [j.id, j]))), expected);
  const newer = [...versions, { job_id: id(8), revision: 4, status: "queued" }];
  const extended = buildLifecyclePhases(newer, [proposal(7, 3, 20), ...proposals], new Map([...map, [id(8), job(id(8), 24, "queued")]]));
  assert.deepEqual(extended.map(p => p.label), [...expected.map(p => p.label), "Revision 3", "Version 4 Render"]);
});

test("actual creation times order renders even when draft revision numbers go backwards", () => {
  const phases = buildLifecyclePhases([{ job_id: id(8), revision: 1, status: "queued" }, ...versions], proposals, new Map([...jobs, job(id(8), 25, "queued")].map(j => [j.id, j])));
  assert.equal(phases.at(-1).id, id(8));
});

test("queued, failed, rejected, stale and ready proposals retain distinct truthful outcomes", () => {
  for (const [state, status, expected] of [["pending", "queued", "Queued — Waiting for AI"], ["pending", "running", "AI processing"], ["pending", "succeeded", "Proposal ready"], ["failed", "failed", "Revision failed"], ["rejected", "failed", "Proposal rejected"], ["stale", "succeeded", "Proposal out of date"]]) {
    const phase = revisionPhase(proposal(3, 1, 4, state, status), 0);
    assert.equal(phase.status, expected);
    assert.ok(!phase.steps.some(step => step.title === "Proposal accepted"));
    if (status === "failed") assert.ok(!phase.steps.some(step => step.title === "Proposal ready"));
  }
  const rejected = revisionPhase(proposal(3, 1, 4, "rejected"), 0);
  assert.equal(rejected.steps.at(-1).state, "rejected");
  assert.equal(rejected.active, false);
  assert.equal(revisionPhase(proposal(3, 1, 4, "accepted"), 0).steps.at(-1).timestamp, undefined);
});

for (const status of ["queued", "running", "succeeded", "failed"]) {
  test(`render ${status} follows list status while job details may lag`, () => {
    const phase = renderPhase({ ...versions[0], status }, job(id(6), 16, "running"));
    assert.equal(phase.active, status === "queued" || status === "running");
    assert.equal(phase.steps.some(step => step.title === "Your video is ready"), status === "succeeded");
    assert.equal(phase.steps.some(step => step.state === "failed"), status === "failed");
    if (status === "succeeded") assert.equal(phase.steps.at(-1).timestamp, null);
  });
}

test("timestamps survive parsing; missing history never invents a stage, time or duration", () => {
  const value = proposal(3, 1, 4);
  assert.equal(parseProposal(value, project).created_at, at(4));
  assert.equal(parseProposal(value, project).finished_at, at(5));
  assert.throws(() => parseProposal({ ...value, created_at: "bad" }, project));
  assert.equal(parseProposal({ ...value, created_at: undefined }, project).created_at, undefined);
  const html = render({ versions, proposals: [{ ...value, created_at: undefined, finished_at: null }] });
  assert.doesNotMatch(html, /NaN|Invalid Date|\d+%|estimated|ETA|Watching your footage|Choosing your story/);
});

test("newest active job remains prominent independently of preview selection and newer terminal history", () => {
  const html = render({ versions: [{ job_id: id(8), revision: 4, status: "failed" }, ...versions], proposals, jobs: [...jobs, job(id(8), 24, "failed")] });
  assert.match(html, /<h3>Version 3 Render · Rendering video<\/h3>/);
  assert.match(html, /Version 4 Render/);
});

test("initial transient status failure keeps recovery polling enabled", () => {
  const { jobPollingInterval } = require("../ai-director/hooks/use-ai-job-status.ts");
  const { ApiError } = require("../../../lib/api/transport.ts");
  assert.equal(jobPollingInterval(undefined, new ApiError("Temporary", 503)), 2000);
  assert.equal(jobPollingInterval("running", new ApiError("Network", 0, "network_error")), 2000);
  assert.equal(jobPollingInterval("succeeded"), false);
  assert.equal(jobPollingInterval("failed"), false);
});
