import test from "node:test";
import assert from "node:assert/strict";

import { parsePublicStoryboard } from "./storyboard-schema.ts";

const valid = {
  target_seconds: 10,
  total_seconds: 5,
  cuts: [
    {
      window_index: 0,
      start_seconds: 0,
      end_seconds: 5,
    },
  ],
};

test("accepts valid public storyboard", () => {
  const result = parsePublicStoryboard(valid);

  assert.equal(result.cuts.length, 1);
  assert.equal(result.total_seconds, 5);
});

test("rejects mismatched timeline", () => {
  assert.throws(() =>
    parsePublicStoryboard({
      ...valid,
      total_seconds: 9,
    }),
  );
});

test("rejects duplicate window index", () => {
  assert.throws(() =>
    parsePublicStoryboard({
      target_seconds: 10,
      total_seconds: 10,
      cuts: [
        { window_index: 0, start_seconds: 0, end_seconds: 5 },
        { window_index: 0, start_seconds: 5, end_seconds: 10 },
      ],
    }),
  );
});

test("rejects invalid source range", () => {
  assert.throws(() =>
    parsePublicStoryboard({
      ...valid,
      cuts: [
        { window_index: 0, start_seconds: 5, end_seconds: 2 },
      ],
    }),
  );
});

test("ignores unknown metadata", () => {
  const result = parsePublicStoryboard({
    ...valid,
    secret: "should-not-be-exposed",
  });

  assert.equal("secret" in result, false);
});