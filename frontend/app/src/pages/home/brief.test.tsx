/**
 * The brief editor's words: what a plan says it looks at, how a template
 * joins the brief, and the sentence a refused save earns. Rendered with no
 * catalog, so a key prints as itself.
 */

import { describe, expect, it } from "vitest";

import { ApiError } from "../../shell/api";
import { TEMPLATES, failureKey, linesIn, planWords, withLine } from "./BriefEditor";
import type { BriefPlan } from "./BriefEditor";

const t = (key: string) => key;

const plan = (over: Partial<BriefPlan>): BriefPlan => ({
  markets: [],
  earnings: null,
  symbols: [],
  topics: [],
  by: "model",
  ...over,
});

describe("what a plan says it looks at", () => {
  it("names each market group, whose results, then the topics", () => {
    expect(
      planWords(
        plan({ markets: ["core", "rates"], earnings: "book", topics: ["insiders"] }),
        t,
      ),
    ).toEqual([
      "home.routine_group_core",
      "home.routine_group_rates",
      "home.routine_earn_book",
      "home.routine_topic_insiders",
    ]);
  });

  it("drops a code this client does not know rather than print it", () => {
    expect(planWords(plan({ markets: ["mars", "spain"], topics: ["tea"] }), t)).toEqual(
      ["home.routine_group_spain"],
    );
  });

  it("says nothing of its own when the plan fetches nothing", () => {
    expect(planWords(plan({}), t)).toEqual([]);
  });
});

describe("withLine", () => {
  const line = "Next week's events";

  it("starts an empty brief", () => {
    expect(withLine("  \n", line)).toBe(line);
  });

  it("adds the line after what the reader wrote", () => {
    expect(withLine("My biggest moves\n", line)).toBe(`My biggest moves\n${line}`);
  });

  it("does not ask twice for what the brief already says", () => {
    const brief = `My biggest moves\n  ${line} `;
    expect(withLine(brief, line)).toBe(brief.replace(/\s+$/, ""));
  });
});

describe("linesIn", () => {
  it("counts the lines that say something — each is a section", () => {
    expect(linesIn("one\n\n two \n")).toBe(2);
    expect(linesIn("")).toBe(0);
  });
});

describe("the templates", () => {
  it("each add a line of their own, keyed by id", () => {
    const ids = TEMPLATES.map((tpl) => tpl.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const tpl of TEMPLATES) expect(tpl.line).toBe(`${tpl.label}_text`);
  });
});

describe("a refused save", () => {
  it("says the memory is full in the server's own words", () => {
    expect(failureKey(new ApiError(409, "home.brief_memory_full"))).toBe(
      "home.brief_memory_full",
    );
  });

  it("says a brief that cannot be kept as it is cannot", () => {
    expect(failureKey(new ApiError(422, "too short"))).toBe("home.brief_unfit");
  });

  it("asks a reader saving in a loop to wait", () => {
    expect(failureKey(new ApiError(429, "chat.rate_limited"))).toBe("home.brief_busy");
  });

  it("falls back to a plain failure for anything else", () => {
    expect(failureKey(new ApiError(409, "not a key"))).toBe("home.brief_error");
    expect(failureKey(new Error("offline"))).toBe("home.brief_error");
  });
});
