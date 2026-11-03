import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  getProjectBySlug,
  isProjectSlug,
  legacyRedirectForStudioSlug,
  listProjects,
  projectStudioPath,
} from "../../../lib/api/projects.ts";
import {
  TAKE_TOUR_EVENT,
  TOUR_STEPS,
  isLastStep,
  placementFor,
  stepIndexAfter,
} from "../studio-tour-logic.ts";

const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
const originalFetch = globalThis.fetch;
process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8011";
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("readable slugs validate and build canonical Studio paths", () => {
  assert.equal(isProjectSlug("a-weekend-in-motion"), true);
  assert.equal(isProjectSlug("my-story-2"), true);
  assert.equal(isProjectSlug("Not A Slug"), false);
  assert.equal(isProjectSlug(""), false);
  assert.equal(isProjectSlug("-leading"), false);
  assert.equal(
    projectStudioPath({ id: project, slug: "a-weekend-in-motion" }),
    "/studio/a-weekend-in-motion",
  );
  // Pre-migration rows without a slug keep the legacy UUID path so no
  // project becomes unreachable before the backfill runs.
  assert.equal(
    projectStudioPath({ id: project.toUpperCase(), slug: null }),
    `/projects/${project}`,
  );
});

test("slug recovery reads the persisted project with GET only", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), method: options?.method ?? "GET" });
    return Response.json({
      id: project,
      name: "A Weekend in Motion",
      slug: "a-weekend-in-motion",
      created_at: "2026-01-01T00:00:00Z",
    });
  };
  const found = await getProjectBySlug("a-weekend-in-motion");
  assert.equal(found.id, project);
  assert.equal(found.slug, "a-weekend-in-motion");
  assert.ok(calls.every((call) => call.method === "GET"));
  assert.ok(calls[0].url.endsWith("/projects/by-slug/a-weekend-in-motion"));
  // Invalid links fail before any network call.
  globalThis.fetch = async () => {
    throw new Error("fetch must not run for invalid slugs");
  };
  await assert.rejects(getProjectBySlug("Not A Slug"), /not valid/);
});

test("project library lists persisted projects newest first shape", async () => {
  globalThis.fetch = async () =>
    Response.json({
      items: [
        {
          id: project,
          name: "Newer story",
          slug: "newer-story",
          created_at: "2026-01-02T00:00:00Z",
        },
        {
          id: "11111111-1111-4111-8111-111111111111",
          name: "Older story",
          slug: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
  const items = await listProjects();
  assert.deepEqual(
    items.map((item) => item.name),
    ["Newer story", "Older story"],
  );
  assert.equal(projectStudioPath(items[0]), "/studio/newer-story");
  assert.equal(
    projectStudioPath(items[1]),
    "/projects/11111111-1111-4111-8111-111111111111",
  );
});

test("legacy UUIDs under /studio/ hand off to the legacy redirect route", () => {
  // Uppercase pastes canonicalize exactly like every other UUID path.
  assert.equal(
    legacyRedirectForStudioSlug(project.toUpperCase()),
    `/projects/${project}`,
  );
  assert.equal(legacyRedirectForStudioSlug(project), `/projects/${project}`);
  // Real slugs and junk never redirect; they resolve or 404 as slugs.
  assert.equal(legacyRedirectForStudioSlug("a-weekend-in-motion"), null);
  assert.equal(legacyRedirectForStudioSlug("Not A Slug"), null);
  assert.equal(legacyRedirectForStudioSlug(""), null);
});

test("tour has the four creator steps in order", () => {
  assert.deepEqual(
    TOUR_STEPS.map((step) => step.id),
    ["media", "director", "timeline", "export"],
  );
  assert.match(TOUR_STEPS[0].title, /Media Library/);
  assert.match(TOUR_STEPS[1].title, /AI Director/);
  assert.match(TOUR_STEPS[2].title, /Timeline/);
  assert.match(TOUR_STEPS[3].title, /Export/);
  // Sequencing clamps at both ends; Finish only exists on the last step.
  assert.equal(stepIndexAfter(0, -1), 0);
  assert.equal(stepIndexAfter(0, 1), 1);
  assert.equal(stepIndexAfter(3, 1), 3);
  assert.equal(isLastStep(3), true);
  assert.equal(isLastStep(2), false);
});

test("tour controls walk forward, back, and stop at Finish", () => {
  // Next walks 0→3, Back walks down, both clamp: Skip/Finish close from
  // any step, so no sequence can run past either end.
  let step = 0;
  step = stepIndexAfter(step, 1);
  step = stepIndexAfter(step, 1);
  assert.equal(step, 2);
  assert.equal(isLastStep(step), false);
  step = stepIndexAfter(step, 1);
  assert.equal(step, 3);
  assert.equal(isLastStep(step), true);
  assert.equal(stepIndexAfter(step, 1), 3);
  assert.equal(stepIndexAfter(step, -1), 2);
  assert.equal(stepIndexAfter(0, -1), 0);
  // Help reopens through one stable event name; nothing is persisted.
  assert.equal(TAKE_TOUR_EVENT, "intentcut:take-tour");
});

test("tour placement falls back safely on mobile, hidden, and off-screen targets", () => {
  const desktop = { width: 1440, height: 900 };
  const rect = { top: 100, bottom: 200, width: 300, height: 100 };
  assert.equal(placementFor(rect, desktop), "below");
  assert.equal(placementFor({ top: 800, bottom: 880, width: 300, height: 80 }, desktop), "above");
  // Mobile always centers, even with room below.
  assert.equal(placementFor(rect, { width: 375, height: 700 }), "center");
  // Missing / hidden targets center instead of spotlighting nothing.
  assert.equal(placementFor(null, desktop), "center");
  assert.equal(placementFor({ top: 0, bottom: 0, width: 0, height: 0 }, desktop), "center");
  // Scrolled out of view centers instead of pointing off-screen. This is
  // the mobile-hidden case: the element exists but cannot be seen.
  assert.equal(placementFor({ top: 1200, bottom: 1300, width: 300, height: 100 }, desktop), "center");
  assert.equal(placementFor({ top: -300, bottom: -100, width: 300, height: 100 }, desktop), "center");
});
