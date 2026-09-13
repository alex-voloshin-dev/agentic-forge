import assert from "node:assert/strict";
import { test } from "node:test";

import { parsePort } from "../src/ports.js";

test("accepts a registered port", () => {
  assert.equal(parsePort("8080"), 8080);
});

test("rejects garbage and out-of-range values", () => {
  assert.throws(() => parsePort("http"), RangeError);
  assert.throws(() => parsePort("70000"), RangeError);
});
