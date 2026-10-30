import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError } from "./transport.ts";

import { createProject } from "./projects.ts";

import {
  listMedia,
  uploadMedia,
} from "./media.ts";

import {
  createAIJob,
  getAIJob,
} from "./ai-jobs.ts";

import {
  listAIArtifacts,
  downloadAIArtifact,
  loadAIArtifactJSON,
} from "./artifacts.ts";

const projectId = "11111111-1111-4111-8111-111111111111";
const mediaId = "22222222-2222-4222-8222-222222222222";
const jobId = "33333333-3333-4333-8333-333333333333";
const artifactId = "44444444-4444-4444-8444-444444444444";
const media = {
  id: mediaId,
  project_id: projectId,
  original_filename: "clip.mp4",
  size_bytes: 100,
  duration_seconds: 4,
  created_at: "2026-10-29T00:00:00Z",
  video: {
    stream_index: 0,
    codec: "h264",
    width: 720,
    height: 1280,
    pixel_format: "yuv420p",
    frame_rate: { numerator: 30, denominator: 1 },
  },
  audio: null,
};
const oldFetch = globalThis.fetch;
process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";

afterEach(() => {
  globalThis.fetch = oldFetch;
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";
});

function json(value, status = 200) {
  return Response.json(value, { status });
}

function once(expectedPath, status, value, assertOptions = () => {}) {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, `http://127.0.0.1:8011${expectedPath}`);
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    assertOptions(options);
    return json(value, status);
  };
}

test("existing createProject export remains functional", async () => {
  once(
    "/projects",
    201,
    { id: projectId, name: "Trip", created_at: "2026-10-29" },
    (o) => {
      assert.equal(o.method, "POST");
      assert.deepEqual(JSON.parse(o.body), { name: "Trip" });
    },
  );
  const created = await createProject("  Trip  ");
  assert.equal(created.id, projectId);
});

test("existing media API remains compatible", async () => {
  once(`/projects/${projectId}/media?limit=100&offset=0`, 200, {
    items: [media],
    limit: 100,
    offset: 0,
  });
  assert.equal((await listMedia(projectId)).items.length, 1);
});

test("upload uses repeated files without a hand-written multipart content-type", async () => {
  once(`/projects/${projectId}/media`, 201, { items: [media] }, (o) => {
    assert.equal(o.method, "POST");
    assert.equal(o.headers, undefined);
    assert.equal(o.body.getAll("files").length, 1);
  });
  const file = new File(["a"], "clip.mp4", { type: "video/mp4" });
  const uploaded = await uploadMedia(projectId, [file]);
  assert.equal(uploaded.items[0].id, mediaId);
});

test("createAIJob validates input and sends exactly the public request shape", async () => {
  once(
    `/projects/${projectId}/ai-jobs`,
    202,
    {
      id: jobId,
      status: "queued",
      status_url: `/projects/${projectId}/ai-jobs/${jobId}`,
    },
    (o) => {
      assert.equal(o.method, "POST");
      assert.deepEqual(JSON.parse(o.body), {
        kind: "first_cut",
        intent: "Tell a story",
        target_seconds: 30,
        media_ids: [mediaId],
      });
    },
  );
  const result = await createAIJob(projectId, {
    kind: "first_cut",
    intent: "  Tell a story  ",
    target_seconds: 30,
    media_ids: [mediaId],
  });
  assert.equal(result.id, jobId);
});

test("invalid AI inputs are rejected before HTTP", async () => {
  globalThis.fetch = () => {
    throw Error("fetch should not execute");
  };
  for (const payload of [
    { kind: "first_cut", intent: "", target_seconds: 30, media_ids: [mediaId] },
    {
      kind: "first_cut",
      intent: "a",
      target_seconds: Infinity,
      media_ids: [mediaId],
    },
    {
      kind: "first_cut",
      intent: "a",
      target_seconds: 30,
      media_ids: [mediaId, mediaId],
    },
  ]) {
    await assert.rejects(createAIJob(projectId, payload), ApiError);
  }
});

test("AI status uses real backend status fields", async () => {
  once(`/projects/${projectId}/ai-jobs/${jobId}`, 200, {
    id: jobId,
    status: "queued",
    created_at: "2026-10-29",
    updated_at: "2026-10-29",
    started_at: null,
    finished_at: null,
    attempt_count: 0,
    error_code: null,
  });
  assert.equal((await getAIJob(projectId, jobId)).status, "queued");
});

test("artifact list validates canonical backend download URLs", async () => {
  const path = `/projects/${projectId}/ai-jobs/${jobId}/artifacts`;
  once(path, 200, {
    items: [
      {
        id: artifactId,
        kind: "video",
        size_bytes: 4,
        download_url: `${path}/${artifactId}`,
      },
    ],
  });
  assert.equal(
    (await listAIArtifacts(projectId, jobId)).items[0].id,
    artifactId,
  );
});

test("artifact list rejects attacker-controlled download URLs", async () => {
  const path = `/projects/${projectId}/ai-jobs/${jobId}/artifacts`;
  once(path, 200, {
    items: [
      {
        id: artifactId,
        kind: "video",
        size_bytes: 4,
        download_url: "https://evil.example/file",
      },
    ],
  });
  await assert.rejects(
    listAIArtifacts(projectId, jobId),
    (error) => error.code === "invalid_response",
  );
});

test("artifact download returns Blob from trusted fixed path", async () => {
  const path = `/projects/${projectId}/ai-jobs/${jobId}/artifacts/${artifactId}`;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, `http://127.0.0.1:8011${path}`);
    assert.equal(options.credentials, "omit");
    return new Response(new Blob(["mp4!"], { type: "video/mp4" }), {
      status: 200,
    });
  };
  const blob = await downloadAIArtifact(projectId, jobId, artifactId);
  assert.equal(await blob.text(), "mp4!");
});

test("artifact JSON preserves unknown structured data without pretending a schema", async () => {
  const path = `/projects/${projectId}/ai-jobs/${jobId}/artifacts/${artifactId}`;
  once(path, 200, { scenes: [{ start_seconds: 0 }] });
  const result = await loadAIArtifactJSON(projectId, jobId, artifactId);
  assert.equal(result.scenes.length, 1);
});

test("HTTP failures are normalized and mutations are never retried", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ code: "ai_api_unavailable", message: "Disabled" }, 503);
  };
  await assert.rejects(
    createAIJob(projectId, {
      kind: "first_cut",
      intent: "a",
      target_seconds: 30,
      media_ids: [mediaId],
    }),
    (error) =>
      error instanceof ApiError &&
      error.status === 503 &&
      error.code === "ai_api_unavailable",
  );
  assert.equal(calls, 1);
});

test("existing local-only base URL restriction remains intact", async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com";
  await assert.rejects(
    listMedia(projectId),
    (error) => error.code === "configuration_error",
  );
});
