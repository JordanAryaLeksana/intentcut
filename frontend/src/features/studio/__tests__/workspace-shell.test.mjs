import "./css-stub.setup.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { StudioDock, dockTabForKey } from "../studio-dock.tsx";
import { renderStateLabel } from "../studio-top-bar.tsx";
import { StoryboardCuts } from "../narrative-timeline.tsx";

// Same React Query entry as the hooks so provider and hooks share context.
const require = createRequire(import.meta.url);
const { QueryClient, QueryClientProvider } = require("@tanstack/react-query");

const storyboard = JSON.parse(readFileSync(new URL("./published-storyboard.json", import.meta.url)));

function renderDock() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(StudioDock)),
  );
}

test("dock exposes labelled tabs and keeps the inactive panel mounted and hidden", () => {
  const html = renderDock();
  assert.match(html, /role="tablist" aria-label="Editing tools"/);
  assert.match(html, /id="dock-tab-director"[^>]*aria-selected="true"[^>]*aria-controls="dock-panel-director"[^>]*tabindex="0"/);
  assert.match(html, /id="dock-tab-inspector"[^>]*aria-selected="false"[^>]*aria-controls="dock-panel-inspector"[^>]*tabindex="-1"/);
  assert.match(html, /id="dock-panel-inspector"[^>]*role="tabpanel"[^>]*hidden=""/);
  for (const tab of ["director", "inspector", "captions", "visuals", "highlights"]) {
    assert.match(html, new RegExp(`id="dock-tab-${tab}"`));
    assert.match(html, new RegExp(`id="dock-panel-${tab}"`));
  }
  assert.equal((html.match(/role="tab"/g) ?? []).length, 5);
  assert.match(html, /Open a project to see details here/);
  assert.match(html, /Create a project and add your footage to begin/);
});

test("dock keyboard navigation wraps and supports Home and End", () => {
  assert.equal(dockTabForKey("director", "ArrowRight"), "inspector");
  assert.equal(dockTabForKey("inspector", "ArrowRight"), "captions");
  assert.equal(dockTabForKey("director", "ArrowLeft"), "highlights");
  assert.equal(dockTabForKey("inspector", "Home"), "director");
  assert.equal(dockTabForKey("director", "End"), "highlights");
  assert.equal(dockTabForKey("captions", "ArrowRight"), "visuals");
  assert.equal(dockTabForKey("visuals", "ArrowRight"), "highlights");
  assert.equal(dockTabForKey("visuals", "ArrowLeft"), "captions");
  assert.equal(dockTabForKey("highlights", "ArrowRight"), "director");
  assert.equal(dockTabForKey("highlights", "ArrowLeft"), "visuals");
  assert.equal(dockTabForKey("director", "Tab"), null);
});

test("toolbar render labels come from actual job status and errors", () => {
  assert.equal(renderStateLabel("queued"), "Waiting to create your video");
  assert.equal(renderStateLabel("running"), "Creating your video…");
  assert.equal(renderStateLabel("succeeded"), "Your video is ready");
  assert.equal(renderStateLabel("failed"), "Your video couldn’t be created");
  assert.equal(renderStateLabel("succeeded", true), "We couldn’t check your video");
  assert.equal(renderStateLabel(), "Checking your video…");
});

test("sequence columns use real source durations in published order, with no edit or seek controls", () => {
  const html = renderToStaticMarkup(createElement(StoryboardCuts, { storyboard }));
  const tracks = /--cut-tracks:([^;]+)/.exec(html)[1].split(" ").map((item) => parseFloat(item));
  assert.deepEqual(tracks, storyboard.cuts.map((cut) => cut.end_seconds - cut.start_seconds));
  assert.ok(Math.abs(tracks.reduce((sum, value) => sum + value, 0) - storyboard.total_seconds) < 1e-6);
  assert.doesNotMatch(html, /<button|role="slider"|draggable|<img/);
});
