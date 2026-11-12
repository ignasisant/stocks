import { describe, expect, it } from "vitest";

import { aboutDay } from "./FeedbackReply";

describe("aboutDay", () => {
  it("names the day a report was sent, in the reader's language", () => {
    expect(aboutDay("2026-11-10T23-59-00Z", "es")).toBe("10 de noviembre");
    expect(aboutDay("2026-11-10T00-01-00Z", "en")).toBe("November 10");
  });

  it("is empty for a stamp it cannot read", () => {
    expect(aboutDay("", "en")).toBe("");
    expect(aboutDay("yesterday", "en")).toBe("");
  });
});
