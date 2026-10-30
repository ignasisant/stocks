import { describe, expect, it } from "vitest";
import { keyBytes } from "./push";

describe("keyBytes", () => {
  it("reads base64url without padding, as the server sends the VAPID key", () => {
    // 0xfb 0xff 0xbf is "-_-_" in base64url and "+/+/" in plain base64.
    expect(Array.from(keyBytes("-_-_"))).toEqual([0xfb, 0xff, 0xbf]);
    expect(Array.from(keyBytes("AQ"))).toEqual([1]);
  });

  it("is the 65-byte uncompressed point a P-256 key encodes to", () => {
    const key = "B" + "A".repeat(86);
    expect(keyBytes(key).length).toBe(65);
    expect(keyBytes(key)[0]).toBe(4);
  });
});
