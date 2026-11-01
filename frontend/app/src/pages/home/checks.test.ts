import { describe, expect, it } from "vitest";

import { EXPLORE, SETUP, setupLine, target, type Row } from "./checks";
import type { TourStep } from "./types";

/** A step as `/onboarding` sends it, with only the fields a target reads. */
function step(
  id: string,
  path: string | null,
  params: Record<string, string> = {},
  session: Record<string, string> = {},
) {
  return {
    id,
    icon: "",
    path,
    params,
    session,
    gated: false,
    done: null,
    title_key: `tour.${id}_title`,
    body_key: `tour.${id}_body`,
    cta_key: null,
  } satisfies TourStep;
}

const STEPS: TourStep[] = [
  step("import", "import_transactions"),
  step("assistant", null, {}, { chat_panel_open: "True" }),
  step("notify", "profile", {}, { profile_tab: "notify" }),
  step("market", "ticker"),
  // No session either: the fallback in `checks.ts` is what names this tab, and
  // one row has to exercise that path.
  step("watchlist", "profile"),
  step("positions", "portfolio", { tab: "positions" }),
  step("prefs", "profile", {}, { profile_tab: "prefs" }),
];

function row(key: string): Row {
  return [...SETUP, ...EXPLORE].find((entry) => entry.key === key)!;
}

describe("target", () => {
  it("rewrites the Streamlit path to this app's slug", () => {
    expect(target(row("import"), STEPS)).toEqual({ kind: "page", page: "import" });
  });

  it("opens the drawer for the step that is not a page", () => {
    // The assistant is a drawer the shell owns, so its rows are not links —
    // but they are still controls, and a row that only reported its state was
    // the one thing on this checklist that could not be acted on.
    expect(target(row("ai"), STEPS)).toEqual({ kind: "assistant" });
    expect(target(row("ask"), STEPS)).toEqual({ kind: "assistant" });
  });

  it("hands the plan to the chat's builder rather than the form", () => {
    expect(target(row("plan"), STEPS)).toEqual({
      kind: "assistant",
      ask: "profile.plan_ask_prompt",
    });
    expect(row("plan").optional).toBe(true);
  });

  it("stays inert for a step with no page and nothing to open", () => {
    const nowhere = [step("assistant", null)];
    expect(target(row("ai"), nowhere)).toBeNull();
  });

  it("names the Profile tab the payload leaves out", () => {
    // From the payload's own `session`, which is what the API now carries.
    expect(target(row("notify"), STEPS)).toEqual({
      kind: "page",
      page: "profile",
      params: { tab: "notify" },
    });
    // And from the local fallback, for a deploy whose API predates it.
    expect(target(row("watchlist"), STEPS)).toEqual({
      kind: "page",
      page: "profile",
      params: { tab: "watch" },
    });
  });

  it("prefers the payload's own tab to the local fallback", () => {
    const moved = [
      step("notify", "profile", { tab: "somewhere" }, { profile_tab: "notify" }),
    ];
    expect(target(row("notify"), moved)).toEqual({
      kind: "page",
      page: "profile",
      params: { tab: "somewhere" },
    });
  });

  it("falls back to nothing when this deploy does not carry the step", () => {
    expect(target(row("import"), [])).toBeNull();
  });

  it("uses the row's own page where no step owns it", () => {
    expect(target(row("login"), [])).toEqual({ kind: "page", page: "profile" });
  });

  it("covers every capability the API reports, and the device's own", () => {
    expect(SETUP.filter((entry) => !entry.device).map((entry) => entry.key)).toEqual([
      "login",
      "import",
      "plan",
      "ai",
      "notify",
    ]);
    expect(SETUP.filter((entry) => entry.device).map((entry) => entry.key)).toEqual([
      "app",
    ]);
    expect(EXPLORE.map((entry) => entry.key)).toEqual(["search", "ask", "watchlist"]);
  });
});

describe("guests", () => {
  it("disables every row whose target sits behind a sign-in, and only those", () => {
    // The import, plan, AI, notifications, app, ask and watchlist rows are disabled
    // for a guest; search stays live, and sign-in is the pending action itself.
    const gated = [...SETUP, ...EXPLORE]
      .filter((entry) => entry.signedIn)
      .map((entry) => entry.key);
    expect(gated).toEqual([
      "import",
      "plan",
      "ai",
      "notify",
      "app",
      "ask",
      "watchlist",
    ]);
  });
});

describe("the app node", () => {
  const server = { login: true, import: true, plan: true, ai: true, notify: true };
  const keys = (line: { row: Row }[]) => line.map((entry) => entry.row.key);

  it("is drawn where this browser can install, still to do", () => {
    for (const way of ["prompt", "ios"] as const) {
      const line = setupLine(server, { guest: false, way, installed: false });
      expect(keys(line).at(-1)).toBe("app");
      expect(line.at(-1)!.on).toBe(false);
    }
  });

  it("is ticked once the app runs installed, whatever the server says", () => {
    // Installed, the browser no longer offers to install: `way` is null.
    const line = setupLine({}, { guest: false, way: null, installed: true });
    expect(line.find((entry) => entry.row.key === "app")!.on).toBe(true);
  });

  it("is left out where nothing can be installed, and for a guest", () => {
    expect(
      keys(setupLine(server, { guest: false, way: null, installed: false })),
    ).not.toContain("app");
    expect(
      keys(setupLine(server, { guest: true, way: "prompt", installed: false })),
    ).not.toContain("app");
  });

  it("does not count towards the setup, and reads only the browser", () => {
    expect(row("app").optional).toBe(true);
    // A key the API might one day send under the same name changes nothing.
    const line = setupLine(
      { app: true },
      { guest: false, way: "prompt", installed: false },
    );
    expect(line.find((entry) => entry.row.key === "app")!.on).toBe(false);
  });

  it("lands on Preferences, where the App card is, when it is not a button", () => {
    expect(target(row("app"), STEPS)).toEqual({
      kind: "page",
      page: "profile",
      params: { tab: "prefs" },
    });
  });
});
