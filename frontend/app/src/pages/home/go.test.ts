import { describe, expect, it } from "vitest";
import { target } from "./Go";

describe("target", () => {
  it("splits a path with its tab", () => {
    expect(target("/profile?tab=plan")).toEqual({
      page: "profile",
      params: { tab: "plan" },
      name: "home.daily_go_plan",
    });
  });

  it("keeps a bare page bare", () => {
    expect(target("/review")).toEqual({
      page: "review",
      params: undefined,
      name: "home.daily_go_review",
    });
  });

  it("draws nothing for a context line or a path it cannot name", () => {
    expect(target("")).toBeNull();
    expect(target(undefined)).toBeNull();
    expect(target("/ticker?ticker=NVDA")).toBeNull();
    expect(target("/profile?tab=keys")).toBeNull();
  });
});
