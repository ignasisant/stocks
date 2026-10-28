import { describe, expect, it } from "vitest";
import { parseBoot } from "./boot";

const ME = { kind: "session", email: "a@b.c" };
const PREFS = { currency: "EUR", language: "es" };

describe("the document's boot block", () => {
  it("reads what the server wrote", () => {
    const text = JSON.stringify({ me: ME, prefs: PREFS, i18n: "abc123" });
    expect(parseBoot(text)).toEqual({ me: ME, prefs: PREFS, i18n: "abc123" });
  });

  it("reads the server's escaped angle brackets back as themselves", () => {
    const text =
      '{"me":{"kind":"session","name":"\\u003cb\\u003e"},"prefs":{"currency":"EUR"}}';
    expect(parseBoot(text)?.me).toEqual({ kind: "session", name: "<b>" });
  });

  it("is null for nothing, for junk, and for a shape it does not know", () => {
    expect(parseBoot(null)).toBeNull();
    expect(parseBoot("")).toBeNull();
    expect(parseBoot("{not json")).toBeNull();
    expect(parseBoot("[]")).toBeNull();
    expect(parseBoot(JSON.stringify({ me: ME }))).toBeNull();
    expect(parseBoot(JSON.stringify({ me: {}, prefs: PREFS }))).toBeNull();
    expect(parseBoot(JSON.stringify({ me: ME, prefs: {} }))).toBeNull();
  });

  it("tolerates a missing catalog stamp", () => {
    expect(parseBoot(JSON.stringify({ me: ME, prefs: PREFS }))?.i18n).toBe("");
  });
});
