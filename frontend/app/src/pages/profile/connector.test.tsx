/**
 * The Claude card: what it offers, what it lists, and when it stays away.
 *
 * Rendered to static markup with no catalog loaded, so every string is its
 * key — which is what these assert against: the question is which parts the
 * card draws for a given answer, not their wording.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Connector, command, day, type Connection } from "./ConnectorCard";

const URL = "https://topstocks.example/mcp";

const connection = (over: Partial<Connection> = {}): Connection => ({
  id: "g_1",
  client_name: "Claude",
  verified: true,
  redirect_host: "claude.ai",
  created: "2026-10-01T09:00:00Z",
  used: "2026-10-02T18:30:00Z",
  expires: "2027-03-30T09:00:00Z",
  ...over,
});

const draw = (url: string | null, connections: Connection[]) =>
  renderToStaticMarkup(
    <Connector url={url} connections={connections} onGone={() => {}} />,
  );

describe("the Claude card", () => {
  it("offers the address and the Claude Code line while the connector is on", () => {
    const html = draw(URL, []);
    expect(html).toContain(URL);
    expect(html).toContain(command(URL));
    expect(html).toContain("profile.connector_none");
  });

  it("draws nothing when there is nothing to offer and nothing to revoke", () => {
    expect(draw(null, [])).toBe("");
  });

  it("keeps a connection revocable after the connector is switched off", () => {
    const html = draw(null, [connection()]);
    expect(html).not.toContain("profile.connector_url");
    expect(html).toContain("profile.connector_revoke");
  });

  it("labels an app that named itself", () => {
    expect(draw(URL, [connection()])).not.toContain("profile.connector_unverified");
    expect(draw(URL, [connection({ verified: false })])).toContain(
      "profile.connector_unverified",
    );
  });

  it("says when an app has not called yet", () => {
    expect(draw(URL, [connection({ used: null })])).toContain(
      "profile.connector_never_used",
    );
  });

  it("escapes the name an app gave itself", () => {
    const html = draw(URL, [
      connection({ client_name: "<img src=x onerror=alert(1)>" }),
    ]);
    expect(html).not.toContain("<img");
  });
});

describe("the card's helpers", () => {
  it("builds the one Claude Code command", () => {
    expect(command(URL)).toBe(`claude mcp add --transport http topstocks ${URL}`);
  });

  it("dates in the reader's language, and nothing for nothing", () => {
    expect(day("2026-10-02T18:30:00Z", "en")).toContain("2026");
    expect(day(null, "en")).toBeNull();
    expect(day("not a date", "en")).toBeNull();
  });
});
