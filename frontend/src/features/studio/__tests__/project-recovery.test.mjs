import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { createAIJob, getAIJob, listAIJobs } from "../../../lib/api/ai-jobs.ts";
import { listAIArtifacts } from "../../../lib/api/artifacts.ts";
import { listMedia } from "../../../lib/api/media.ts";
import { getProject } from "../../../lib/api/projects.ts";
import { canonicalId } from "../../../lib/api/transport.ts";
import {
  latestRecoverableJobId,
  readSavedJobId,
  removeSavedJobId,
  writeSavedJobId,
} from "../store/job-recovery.ts";
import { useEditorStore } from "../store/use-editor-store.ts";

const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
const upperProject = project.toUpperCase();
const job = "44c3fa22-3ee4-43ec-a476-3e99172c9af2";
const olderJob = "11111111-1111-4111-8111-111111111111";
const mediaId = "22222222-2222-4222-8222-222222222222";
const artifactId = "b43e8613-09a4-4187-98f1-ad23d5653c09";
const originalFetch = globalThis.fetch;
process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";
afterEach(() => {
  globalThis.fetch = originalFetch;
  useEditorStore.setState({ activeJobByProject: {} });
});

const mediaBody = {
  items: [{
    id: mediaId, project_id: project, original_filename: "clip.mp4",
    size_bytes: 10, duration_seconds: 5, created_at: "2026-01-01T00:00:00Z",
    video: { stream_index: 0, codec: "h264", width: 640, height: 360, pixel_format: "yuv420p", frame_rate: { numerator: 30, denominator: 1 } },
    audio: null,
  }],
  limit: 100, offset: 0,
};
const jobBody = (id, status) => ({
  id, status, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  started_at: null, finished_at: null, attempt_count: 1, error_code: null, progress: null,
});

test("a valid project reopened with a differently-cased URL still loads", async () => {
  assert.equal(canonicalId(upperProject), project);
  globalThis.fetch = async (url) => {
    const text = String(url);
    if (text.includes("/media")) return Response.json(mediaBody);
    if (text.includes("/artifacts")) {
      return Response.json({ items: [{ id: artifactId, kind: "video", size_bytes: 100, download_url: `/projects/${project}/ai-jobs/${job}/artifacts/${artifactId}` }] });
    }
    if (text.endsWith("/ai-jobs")) {
      return Response.json({ id: job, status: "queued", status_url: `/projects/${project}/ai-jobs/${job}` }, { status: 202 });
    }
    return Response.json(jobBody(job, "succeeded"));
  };
  // Media, artifacts, creation, and status all survive the case change.
  assert.equal((await listMedia(upperProject)).items[0].id, mediaId);
  assert.equal((await listAIArtifacts(upperProject, job)).items[0].id, artifactId);
  assert.equal(
    (await createAIJob(upperProject, { kind: "first_cut", intent: "story", target_seconds: 30, media_ids: [mediaId] })).id,
    job,
  );
  assert.equal((await getAIJob(upperProject, job.toUpperCase())).status, "succeeded");
});

test("reopen reads the persisted project and server jobs without mutating", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), method: options?.method ?? "GET" });
    if (String(url).endsWith(`/projects/${project}`)) {
      return Response.json({ id: project, name: "Reopened story", created_at: "2026-01-01T00:00:00Z" });
    }
    return Response.json({ items: [jobBody(job, "succeeded"), jobBody(olderJob, "failed")] });
  };
  assert.equal((await getProject(upperProject)).name, "Reopened story");
  const jobs = await listAIJobs(project);
  assert.deepEqual(jobs.map((item) => item.id), [job, olderJob]);
  assert.ok(calls.every((call) => call.method === "GET"));
  // Newest non-failed wins; a failed newest job never blocks resubmission.
  assert.equal(latestRecoverableJobId(jobs), job);
  assert.equal(latestRecoverableJobId([jobBody(olderJob, "failed")]), null);
  assert.equal(latestRecoverableJobId([]), null);
});

test("session recovery round-trips canonically and forgets rejected jobs", () => {
  const entries = new Map();
  const storage = {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  };
  writeSavedJobId(upperProject, storage, job.toUpperCase());
  assert.equal(readSavedJobId(project, storage), job);
  assert.equal(readSavedJobId(olderJob, storage), null);
  removeSavedJobId(project, storage);
  assert.equal(readSavedJobId(project, storage), null);
  // Broken storage never throws into Studio startup.
  const blocked = {
    getItem: () => { throw new Error("Blocked"); },
    setItem: () => { throw new Error("Blocked"); },
    removeItem: () => { throw new Error("Blocked"); },
  };
  writeSavedJobId(project, blocked, job);
  removeSavedJobId(project, blocked);
  assert.equal(readSavedJobId(project, blocked), null);
});

test("clearing a rejected job leaves other projects untouched", () => {
  const store = useEditorStore.getState();
  store.setActiveJob(project, job);
  store.setActiveJob(olderJob, olderJob);
  store.clearActiveJob(project);
  assert.equal(useEditorStore.getState().activeJobByProject[project], undefined);
  assert.equal(useEditorStore.getState().activeJobByProject[olderJob], olderJob);
  store.clearActiveJob(project);
  assert.equal(useEditorStore.getState().activeJobByProject[olderJob], olderJob);
});
