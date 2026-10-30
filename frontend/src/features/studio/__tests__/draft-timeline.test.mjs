import test, { beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");
function render(component) {
  const client = new QueryClient({defaultOptions:{queries:{retry:false, gcTime:Infinity}}});
  const result = renderToStaticMarkup(createElement(QueryClientProvider,{client},component));
  client.clear(); return result;
}
import { useDraftStore, isDraftDirty } from "../store/use-draft-store.ts";
import { DraftTimeline, DraftControls } from "../draft-timeline.tsx";
import { parsePublicStoryboard } from "../ai-director/storyboard/storyboard-schema.ts";

const storyboard = parsePublicStoryboard(JSON.parse(readFileSync(new URL("./published-storyboard.json", import.meta.url))));
const base = { jobId: "job-a", artifactId: "artifact-a" };
const next = { jobId: "job-b", artifactId: "artifact-b" };
const store = () => useDraftStore.getState();
const draft = (project = "p") => store().byProject[project];
beforeEach(() => {
  useDraftStore.setState({ byProject: {}, dockTabByProject: {}, savedByProject:{}, restoredByProject:{}, previewByProject:{} });
  store().receive("p", base, storyboard);
});

test("initial draft keeps five actual cuts in published order without mutating artifact", () => {
  assert.deepEqual(draft().cuts.map(c => c.window_index), [2, 6, 4, 8, 5]);
  assert.equal(isDraftDirty(draft()), false);
  const before = structuredClone(storyboard);
  store().move("p", draft().cuts[0].id, 1);
  assert.deepEqual(storyboard, before);
  assert.equal(isDraftDirty(draft()), true);
});

test("selection opens Inspector without creating an edit or invalid selection", () => {
  const id = draft().cuts[2].id;
  store().select("p", id);
  assert.equal(draft().selectedId, id);
  assert.equal(store().dockTabByProject.p, "inspector");
  assert.equal(draft().revision, 0);
  store().select("p", "missing");
  assert.equal(draft().selectedId, id);
});

test("move boundaries are no-ops; reorder preserves identity, ranges and precise total", () => {
  const original = draft();
  const id = original.cuts[0].id;
  store().move("p", id, -1);
  assert.equal(draft(), original);
  store().move("p", id, 1);
  assert.deepEqual(draft().cuts.map(c => c.window_index), [6, 2, 4, 8, 5]);
  assert.equal(draft().cuts[1], original.cuts[0]);
  const total = draft().cuts.reduce((sum, c) => sum + c.end_seconds - c.start_seconds, 0);
  assert.ok(Math.abs(total - 18.823334) < 1e-9);
  assert.notEqual(total, storyboard.render_seconds);
});

test("remove supports empty draft, repairs selection and undo restores exact state", () => {
  for (const cut of [...draft().cuts]) {
    store().select("p", cut.id);
    store().remove("p", cut.id);
  }
  assert.equal(draft().cuts.length, 0);
  assert.equal(draft().selectedId, null);
  const html = render(createElement(DraftTimeline, { projectId: "p", draft: draft() }));
  assert.match(html, /Draft is empty/);
  for (let i = 0; i < 5; i++) store().undo("p");
  assert.deepEqual(draft().cuts.map(c => c.window_index), [2, 6, 4, 8, 5]);
  assert.equal(isDraftDirty(draft()), false);
});

test("undo and redo restore deterministic order and selection; branching clears redo", () => {
  const id = draft().cuts[0].id;
  store().select("p", id);
  store().move("p", id, 1);
  store().remove("p", id);
  store().undo("p");
  assert.equal(draft().selectedId, id);
  assert.equal(draft().cuts[1].id, id);
  store().redo("p");
  assert.equal(draft().cuts.length, 4);
  store().undo("p"); store().undo("p");
  assert.equal(draft().cuts[0].id, id);
  store().move("p", id, 1);
  assert.equal(draft().future.length, 0);
});

test("same artifact refetch preserves edits, selection, history and object identity", () => {
  store().move("p", draft().cuts[0].id, 1);
  const edited = draft();
  store().receive("p", base, structuredClone(storyboard));
  assert.equal(draft(), edited);
});

test("new AI result is a proposal for dirty drafts and requires explicit replacement", () => {
  store().remove("p", draft().cuts[0].id);
  store().receive("p", next, storyboard);
  assert.equal(draft().base.jobId, base.jobId);
  assert.equal(draft().cuts.length, 4);
  assert.deepEqual(draft().pending.base, next);
  store().acceptPending("p");
  assert.deepEqual(draft().base, next);
  assert.equal(draft().cuts.length, 5);
  assert.equal(draft().past.length, 0);
  assert.equal(isDraftDirty(draft()), false);
});

test("new clean result replaces baseline and project histories remain isolated", () => {
  store().receive("other", next, storyboard);
  const other = draft("other");
  store().remove("p", draft().cuts[0].id);
  store().undo("other");
  assert.equal(draft("other"), other);
  assert.equal(draft().cuts.length, 4);
  store().undo("p");
  store().receive("p", next, storyboard);
  assert.deepEqual(draft().base, next);
  assert.equal(draft().revision, 0);
  assert.equal(draft("other"), other);
});

test("accessible controls expose real disabled states and selected state", () => {
  let html = render(createElement(DraftControls, { projectId: "p", draft: draft() }));
  assert.equal((html.match(/disabled=""/g) ?? []).length, 3);
  store().select("p", draft().cuts[0].id);
  html = render(createElement(DraftControls, { projectId: "p", draft: draft() }));
  assert.equal((html.match(/disabled=""/g) ?? []).length, 1);
  html = render(createElement(DraftTimeline, { projectId: "p", draft: draft() }));
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /Unsaved draft changes/);
  assert.doesNotMatch(html, /Render Changes|draggable|playhead/i);
});

test("editorial reason is preserved only when supplied, without inventing metadata", () => {
  assert.equal(storyboard.cuts[0].editorial_reason, undefined);
  const supplied = { ...storyboard, cuts: storyboard.cuts.map(c => ({ ...c, editorial_reason: "Actual published reason" })) };
  assert.equal(parsePublicStoryboard(supplied).cuts[0].editorial_reason, "Actual published reason");
  assert.throws(() => parsePublicStoryboard({ ...storyboard, cuts: storyboard.cuts.map(c => ({ ...c, editorial_reason: 123 })) }));
});
