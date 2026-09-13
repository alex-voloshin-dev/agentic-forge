import { describe, expect, it } from "vitest";

import { parsePort } from "./ports";

describe("parsePort", () => {
  it("accepts a registered port", () => {
    expect(parsePort("8080")).toBe(8080);
  });

  it("rejects garbage and out-of-range values", () => {
    expect(() => parsePort("http")).toThrow(RangeError);
    expect(() => parsePort("70000")).toThrow(RangeError);
  });
});
