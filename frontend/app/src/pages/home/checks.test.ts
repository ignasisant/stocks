import { describe, expect, it } from "vitest";

import { EXPLORE, SETUP, target, type Row } from "./checks";
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

  it("stays inert for a step with no page and nothing to open", () => {
    const nowhere = [step("assistant", null)];
    expect(target(row("ai"), nowhere)).toBeNull();
  });

  it("names the Profile tab the payload leaves out", () => {
    // From the payload's own `session`, which is what the API now carries.
    expect(target(row("telegram"), STEPS)).toEqual({
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
    expect(target(row("telegram"), moved)).toEqual({
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

  it("covers every capability the API reports", () => {
    expect(SETUP.map((entry) => entry.key)).toEqual([
      "login",
      "import",
      "ai",
      "telegram",
    ]);
    expect(EXPLORE.map((entry) => entry.key)).toEqual(["search", "ask", "watchlist"]);
  });
});
