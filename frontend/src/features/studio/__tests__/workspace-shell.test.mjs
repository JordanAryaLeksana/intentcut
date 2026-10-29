import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { StudioDock, dockTabForKey } from "../studio-dock.tsx";
import { renderStateLabel } from "../studio-top-bar.tsx";
import { StoryboardCuts } from "../narrative-timeline.tsx";

const storyboard = JSON.parse(readFileSync(new URL("./published-storyboard.json", import.meta.url)));

test("dock exposes labelled tabs and keeps the inactive panel mounted and hidden", () => {
  const html = renderToStaticMarkup(createElement(StudioDock));
  assert.match(html, /role="tablist" aria-label="Editing tools"/);
  assert.match(html, /id="dock-tab-director"[^>]*aria-selected="true"[^>]*aria-controls="dock-panel-director"[^>]*tabindex="0"/);
  assert.match(html, /id="dock-tab-inspector"[^>]*aria-selected="false"[^>]*aria-controls="dock-panel-inspector"[^>]*tabindex="-1"/);
  assert.match(html, /id="dock-panel-inspector"[^>]*role="tabpanel"[^>]*hidden=""/);
  assert.match(html, /Open a project to inspect its saved footage/);
  assert.match(html, /Create a project and upload footage to begin/);
});

test("dock keyboard navigation wraps and supports Home and End", () => {
  assert.equal(dockTabForKey("director", "ArrowRight"), "inspector");
  assert.equal(dockTabForKey("inspector", "ArrowRight"), "director");
  assert.equal(dockTabForKey("director", "ArrowLeft"), "inspector");
  assert.equal(dockTabForKey("inspector", "Home"), "director");
  assert.equal(dockTabForKey("director", "End"), "inspector");
  assert.equal(dockTabForKey("director", "Tab"), null);
});

test("toolbar render labels come from actual job status and errors", () => {
  assert.equal(renderStateLabel("queued"), "First cut queued");
  assert.equal(renderStateLabel("running"), "Processing first cut");
  assert.equal(renderStateLabel("succeeded"), "First cut rendered");
  assert.equal(renderStateLabel("failed"), "First cut failed");
  assert.equal(renderStateLabel("succeeded", true), "Job unavailable");
  assert.equal(renderStateLabel(), "Checking job");
});

test("sequence columns use real source durations in published order, with no edit or seek controls", () => {
  const html = renderToStaticMarkup(createElement(StoryboardCuts, { storyboard }));
  const tracks = /--cut-tracks:([^;]+)/.exec(html)[1].split(" ").map((item) => parseFloat(item));
  assert.deepEqual(tracks, storyboard.cuts.map((cut) => cut.end_seconds - cut.start_seconds));
  assert.ok(Math.abs(tracks.reduce((sum, value) => sum + value, 0) - storyboard.total_seconds) < 1e-6);
  assert.doesNotMatch(html, /<button|role="slider"|draggable|<img/);
});
