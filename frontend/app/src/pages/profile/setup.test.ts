import { describe, expect, it } from "vitest";
import { nextSetup } from "./setup";

describe("the next setup step", () => {
  it("points at the first capability still off", () => {
    expect(
      nextSetup({ login: true, import: true, plan: false, notify: false }),
    ).toEqual({
      key: "plan",
      page: "profile",
      params: { tab: "plan" },
    });
  });
  it("is nothing when everything is on", () => {
    expect(nextSetup({ login: true, import: true, plan: true })).toBeNull();
  });
});
