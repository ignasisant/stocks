/**
 * The MCP card: what it offers, what it lists, and when it stays away.
 *
 * Rendered to static markup with no catalog loaded, so every string is its
 * key — which is what these assert against: the question is which parts the
 * card draws for a given answer, not their wording.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  APPS,
  Connector,
  day,
  knownApp,
  setup,
  source,
  type App,
  type Connection,
} from "./ConnectorCard";

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

const draw = (url: string | null, connections: Connection[], app?: App) =>
  renderToStaticMarkup(
    <Connector url={url} connections={connections} onGone={() => {}} app={app} />,
  );

describe("the MCP card", () => {
  it("offers the address and every app while the connector is on", () => {
    const html = draw(URL, []);
    expect(html).toContain(URL);
    for (const name of ["Claude", "Claude Code", "ChatGPT", "Codex", "Gemini CLI"]) {
      expect(html).toContain(`>${name}<`);
    }
    expect(html).toContain("profile.connector_app_other");
    expect(html).toContain("profile.connector_none");
  });

  it("opens on Claude, whose setup is its own settings screen", () => {
    const html = draw(URL, []);
    expect(html).toContain("profile.connector_how_claude");
    expect(html).toContain("profile.connector_plans");
    expect(html).not.toContain("profile.connector_copy_command");
  });

  it("draws the picked app's setup line, ready to copy", () => {
    const html = draw(URL, [], "codex");
    expect(html).toContain("profile.connector_how_codex");
    expect(html).toContain(`codex mcp add topstocks --url ${URL}`);
    expect(html).toContain("profile.connector_copy_command");
    expect(html).toContain("profile.connector_after_codex");
    expect(html).not.toContain("profile.connector_plans");
  });

  it("says it is connected once an app is", () => {
    expect(draw(URL, [])).not.toContain("profile.connector_ok");
    expect(draw(URL, [connection()])).toContain("profile.connector_ok");
  });

  it("says it is not connected yet while the door is open and nobody is in", () => {
    expect(draw(URL, [])).toContain("profile.connector_wait");
    expect(draw(URL, [connection()])).not.toContain("profile.connector_wait");
    // The connector off, a grant from before: still connected, never waiting.
    expect(draw(null, [connection()])).toContain("profile.connector_ok");
    expect(draw(null, [connection()])).not.toContain("profile.connector_wait");
  });

  it("names where an app returns to, unless that is the reader's own machine", () => {
    expect(draw(URL, [connection()])).toContain("profile.connector_returns_to");
    for (const host of ["localhost", "127.0.0.1", "::1"]) {
      expect(draw(URL, [connection({ redirect_host: host })])).not.toContain(
        "profile.connector_returns_to",
      );
    }
  });

  it("reports only the sources the server accepts", () => {
    expect(source("chat")).toBe("chat");
    expect(source("news")).toBe("news");
    expect(source(null)).toBe("profile");
    expect(source("elsewhere")).toBe("profile");
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
  it("builds each app's setup line around the address", () => {
    expect(setup("claude_code", URL)).toBe(
      `claude mcp add --transport http topstocks ${URL}`,
    );
    expect(setup("gemini", URL)).toBe(
      `gemini mcp add --transport http topstocks ${URL}`,
    );
    expect(setup("other", URL)).toBe(`npx -y mcp-remote ${URL}`);
    for (const app of ["claude", "chatgpt", "lechat"] as const) {
      expect(setup(app, URL)).toBeNull();
    }
  });

  it("writes config files the editors parse, under each one's own keys", () => {
    expect(JSON.parse(setup("cursor", URL) ?? "")).toEqual({
      mcpServers: { topstocks: { url: URL } },
    });
    expect(JSON.parse(setup("windsurf", URL) ?? "")).toEqual({
      mcpServers: { topstocks: { serverUrl: URL } },
    });
    const vscode = setup("vscode", URL) ?? "";
    expect(JSON.parse(vscode.slice(vscode.indexOf("'") + 1, -1))).toEqual({
      name: "topstocks",
      type: "http",
      url: URL,
    });
  });

  it("opens only on an app it knows", () => {
    expect(knownApp("chatgpt")).toBe("chatgpt");
    expect(knownApp("elsewhere")).toBeUndefined();
    expect(knownApp(null)).toBeUndefined();
    expect(APPS).toContain("other");
  });

  it("dates in the reader's language, and nothing for nothing", () => {
    expect(day("2026-10-02T18:30:00Z", "en")).toContain("2026");
    expect(day(null, "en")).toBeNull();
    expect(day("not a date", "en")).toBeNull();
  });
});
