import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

// Load React, React Query, and the component through one CommonJS
// instance: the tsx-compiled component uses the CJS builds, and a second
// ESM copy would provide a different QueryClient context.
const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
const { HighlightNavigator } = require("../highlights/highlight-navigator.tsx");
const { readSavedJobId, writeSavedJobId } = require("../store/job-recovery.ts");

const PROJECT_ID = "11111111-2222-3333-4444-555555555555";
const MEDIA_ID = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";

function renderNavigator({ projectId, seed } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (seed) seed(client);
  return renderToStaticMarkup(
    React.createElement(
      QueryClientProvider,
      { client },
      React.createElement(HighlightNavigator, { projectId }),
    ),
  );
}

function seedMedia(client) {
  client.setQueryData(["projects", PROJECT_ID, "media"], [
    {
      id: MEDIA_ID,
      original_filename: "long-take.mp4",
      duration_seconds: 3600,
    },
  ]);
}

function seedCandidates(client, candidates) {
  client.setQueryData(
    ["projects", PROJECT_ID, "highlight-candidates", MEDIA_ID],
    {
      media_id: MEDIA_ID,
      duration_seconds: 3600,
      sha256: "ab".repeat(32),
      candidates,
    },
  );
}

const CANDIDATE = {
  id: "hl-01",
  media_id: MEDIA_ID,
  start_seconds: 813,
  end_seconds: 821,
  score: 0.87,
  components: { exposure: 0.5, color: 0.6, sharpness: 0.7 },
  heuristic_only: true,
};

test("navigator mounts without crashing when query data is undefined", () => {
  // No project: every query is disabled, so candidate data stays undefined.
  // Regression: an unstable `?? []` fallback made the render-phase sync
  // guard fire on every render ("Too many re-renders", React #301).
  const html = renderNavigator({ projectId: undefined });
  assert.match(html, /Open a project to discover highlight candidates\./);
});

test("navigator mounts without crashing when the candidate list is empty", () => {
  const html = renderNavigator({
    projectId: PROJECT_ID,
    seed: (client) => {
      seedMedia(client);
      seedCandidates(client, []);
    },
  });
  assert.match(html, /No candidate moments survived deduplication/);
});

test("navigator survives repeated renders with stable output", () => {
  const first = renderNavigator({ projectId: undefined });
  for (let i = 0; i < 3; i += 1) {
    assert.equal(renderNavigator({ projectId: undefined }), first);
  }
});

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
  };
}

test("job recovery round-trips the active job per project", () => {
  const storage = fakeStorage();
  const jobId = "22222222-3333-4444-5555-666666666666";
  const otherProject = "99999999-8888-7777-6666-555555555555";
  assert.equal(readSavedJobId(PROJECT_ID, storage), null);
  writeSavedJobId(PROJECT_ID, storage, jobId);
  assert.equal(readSavedJobId(PROJECT_ID, storage), jobId);
  // Project isolation: another project never inherits this job.
  assert.equal(readSavedJobId(otherProject, storage), null);
  // Invalid identifiers are never persisted or restored.
  writeSavedJobId(PROJECT_ID, storage, "not-a-uuid");
  assert.equal(readSavedJobId(PROJECT_ID, storage), jobId);
  writeSavedJobId("not-a-project", storage, jobId);
  assert.equal(readSavedJobId("not-a-project", storage), null);
});

test("navigator renders candidates when discovery data is present", () => {
  const html = renderNavigator({
    projectId: PROJECT_ID,
    seed: (client) => {
      seedMedia(client);
      seedCandidates(client, [CANDIDATE]);
    },
  });
  assert.match(html, /hl-01/);
  assert.match(html, /00:13:33/);
  assert.match(html, /Generate Highlights/);
});
