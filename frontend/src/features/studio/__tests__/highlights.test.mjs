import test from "node:test";
import assert from "node:assert/strict";
import {
  formatTimestamp,
  markerPercent,
  matchStoryboardCut,
} from "../highlights/highlight-format.ts";
import { parseCandidateList } from "../../../lib/api/highlights.ts";

test("formatTimestamp renders hour-scale source positions", () => {
  assert.equal(formatTimestamp(0), "00:00:00");
  assert.equal(formatTimestamp(8130), "02:15:30");
  assert.equal(formatTimestamp(8138.9), "02:15:38");
  assert.equal(formatTimestamp(6 * 3600), "06:00:00");
  assert.equal(formatTimestamp(-1), "--:--:--");
});

test("markerPercent clamps markers to the proportional track", () => {
  assert.deepEqual(markerPercent(8130, 8138, 21600), {
    left: "37.639%",
    width: "0.037%",
  });
  assert.deepEqual(markerPercent(0, 8, 0), { left: "0%", width: "0%" });
  const edge = markerPercent(21595, 21605, 21600);
  assert.ok(Number.parseFloat(edge.left) <= 100);
});

test("matchStoryboardCut only matches exact original offsets", () => {
  const candidate = {
    id: "hl-01",
    media_id: "m",
    start_seconds: 8130,
    end_seconds: 8138,
    score: 0.9,
    components: {},
    heuristic_only: true,
  };
  const cuts = [
    { start_seconds: 8130, end_seconds: 8138, editorial_reason: "climax", playback_order: 1 },
    { start_seconds: 0, end_seconds: 8, editorial_reason: "hook", playback_order: 0 },
  ];
  assert.deepEqual(matchStoryboardCut(candidate, cuts), {
    start_seconds: 8130,
    end_seconds: 8138,
    editorial_reason: "climax",
    playback_order: 1,
  });
  assert.equal(
    matchStoryboardCut({ ...candidate, start_seconds: 8130.5 }, cuts),
    null,
  );
});

test("parseCandidateList rejects placeholder-shaped payloads", () => {
  const media = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
  const good = {
    media_id: media,
    duration_seconds: 3600,
    sha256: "ab".repeat(32),
    candidates: [
      {
        id: "hl-01",
        media_id: media,
        start_seconds: 10,
        end_seconds: 18,
        score: 0.7,
        components: { exposure: 0.5 },
        heuristic_only: true,
      },
    ],
  };
  assert.equal(parseCandidateList(good).candidates.length, 1);
  assert.equal(parseCandidateList({ ...good, candidates: [] }).candidates.length, 0);
  assert.throws(() =>
    parseCandidateList({
      ...good,
      candidates: [{ ...good.candidates[0], heuristic_only: false }],
    }),
  );
  assert.throws(() => parseCandidateList({ ...good, media_id: "not-a-uuid" }));
});
