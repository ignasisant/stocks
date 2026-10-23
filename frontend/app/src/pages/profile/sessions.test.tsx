/**
 * The signed-in devices block: what it draws for an answer, and what its
 * buttons call. Static markup with no catalog loaded, so strings are keys.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { SessionList, ago, type SessionRow } from "./Sessions";

const row = (over: Partial<SessionRow> = {}): SessionRow => ({
  id: "a1",
  device: "Chrome · macOS",
  created: 1000,
  seen: 2000,
  current: false,
  ...over,
});

const draw = (rows: SessionRow[], onEnd = () => {}, onEndOthers = () => {}) =>
  renderToStaticMarkup(
    <SessionList
      rows={rows}
      busy={null}
      failure={null}
      onEnd={onEnd}
      onEndOthers={onEndOthers}
    />,
  );

describe("the signed-in devices block", () => {
  it("lists each device and marks this one", () => {
    const html = draw([
      row({ id: "me", current: true }),
      row({ id: "x", device: "Safari · iOS" }),
    ]);
    expect(html).toContain("Chrome · macOS");
    expect(html).toContain("Safari · iOS");
    expect(html.match(/profile\.sessions_this/g)).toHaveLength(1);
  });

  it("offers a sign-out for the others only, and one for all of them", () => {
    const html = draw([row({ id: "me", current: true }), row({ id: "x" })]);
    expect(html.match(/profile\.sessions_end"?</g)).toHaveLength(1);
    expect(html).toContain("profile.sessions_end_others");
  });

  it("has nothing to end when this is the only device", () => {
    const html = draw([row({ current: true })]);
    expect(html).not.toContain("profile.sessions_end_others");
    expect(html).not.toContain(">profile.sessions_end<");
  });

  it("says unknown for a browser it could not read", () => {
    expect(draw([row({ device: "" })])).toContain("profile.sessions_unknown");
  });

  it("escapes a device name", () => {
    expect(draw([row({ device: "<img src=x onerror=1>" })])).not.toContain("<img");
  });

  it("dates last activity coarsely", () => {
    expect(ago(1000, "en", 1100)).toBe("now");
    expect(ago(0, "en", 3 * 86400)).toBe("3 days ago");
  });
});

describe("the buttons call the API", () => {
  it("DELETEs one session, then the others", async () => {
    const calls: [string, string][] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: { method: string }) => {
        calls.push([init.method, url]);
        return new Response(JSON.stringify({ ended: 1 }), { status: 200 });
      }),
    );
    const { send } = await import("../../shell/api");
    await send("DELETE", `/account/sessions/${encodeURIComponent("a1")}`);
    await send("DELETE", "/account/sessions/others");
    expect(calls).toEqual([
      ["DELETE", "/api/v1/account/sessions/a1"],
      ["DELETE", "/api/v1/account/sessions/others"],
    ]);
    vi.unstubAllGlobals();
  });
});
