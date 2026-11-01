import { describe, expect, it } from "vitest";
import { zoneToSend } from "./zone";

describe("zoneToSend", () => {
  it("sends the browser's zone when the account has none or another", () => {
    expect(zoneToSend("Europe/Madrid", null)).toBe("Europe/Madrid");
    expect(zoneToSend("America/New_York", "Europe/Madrid")).toBe("America/New_York");
  });

  it("sends nothing when it is already stored or the browser will not say", () => {
    expect(zoneToSend("Europe/Madrid", "Europe/Madrid")).toBeNull();
    expect(zoneToSend(null, "Europe/Madrid")).toBeNull();
  });
});
