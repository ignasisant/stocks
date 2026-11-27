/**
 * The Learn page's parts: where a path stands, what a search finds, and what
 * the paths, a lesson and the glossary draw.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TermList } from "./Glossary";
import { figure } from "./Live";
import { LessonBody, Quiz } from "./Lesson";
import {
  appTarget,
  blocks,
  fold,
  guestDone,
  matching,
  pathKey,
  place,
  shownAliases,
  setGuestDone,
  standing,
  highlight,
  inPath,
  lessonPaths,
  nextUp,
  termOfDay,
  toggled,
} from "./logic";
import Paths from "./Paths";
import type { Curriculum, Lesson, Term } from "./types";

const curriculum: Curriculum = {
  paths: [
    {
      id: "start",
      icon: "lightbulb",
      lessons: [
        { id: "a", title: "A", minutes: 3 },
        { id: "b", title: "B", minutes: 4 },
      ],
    },
    {
      id: "tax-es",
      icon: "account_balance",
      lessons: [{ id: "c", title: "C", minutes: 5 }],
    },
  ],
  done: [],
  terms: 2,
};

const terms: Term[] = [
  {
    id: "pe",
    label: "PER",
    aliases: ["P/E"],
    desc: "Precio entre beneficio.",
    lesson: null,
  },
  {
    id: "index",
    label: "Índice",
    aliases: [],
    desc: "Cesta de valores.",
    lesson: { id: "a", title: "A", minutes: 3 },
  },
];

const lesson: Lesson = {
  id: "b",
  path: "start",
  title: "B",
  minutes: 4,
  as_of: "2026-10-25",
  body: "## Idea\n\nTexto.",
  app: "portfolio?tab=risk",
  terms: [{ id: "pe", label: "PER", desc: "Precio entre beneficio." }],
  before: { id: "a", title: "A", minutes: 3 },
  after: null,
  done: false,
};

const memory = (): Storage => {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (k) => items.get(k) ?? null,
    key: (i) => [...items.keys()][i] ?? null,
    removeItem: (k) => void items.delete(k),
    setItem: (k, v) => void items.set(k, v),
  };
};

describe("logic", () => {
  it("names a path's catalog keys without hyphens", () => {
    expect(pathKey("tax-es")).toBe("tax_es");
  });

  it("counts what is read and opens the first unread lesson", () => {
    const path = curriculum.paths[0]!;
    expect(standing(path, new Set())).toEqual({ read: 0, total: 2, next: "a" });
    expect(standing(path, new Set(["a"]))).toEqual({ read: 1, total: 2, next: "b" });
    expect(standing(path, new Set(["a", "b"])).next).toBeNull();
  });

  it("places a lesson in its path", () => {
    expect(place(curriculum, "b")).toEqual({ at: 2, total: 2 });
    expect(place(curriculum, "c")).toEqual({ at: 1, total: 1 });
    expect(place(curriculum, "gone")).toBeNull();
  });

  it("reads an in-app link into a page and its query", () => {
    expect(appTarget("portfolio?tab=risk")).toEqual({
      page: "portfolio",
      params: { tab: "risk" },
    });
    expect(appTarget("import")).toEqual({ page: "import" });
    expect(appTarget("")).toBeNull();
  });

  it("finds a term whatever the accents and case, label first", () => {
    expect(fold("Índice")).toBe("indice");
    expect(matching(terms, "indice").map((t) => t.id)).toEqual(["index"]);
    expect(matching(terms, "p/e").map((t) => t.id)).toEqual(["pe"]);
    expect(matching(terms, "cesta").map((t) => t.id)).toEqual(["index"]);
    expect(matching(terms, "")).toHaveLength(2);
  });

  it("keeps a guest's ticks in the browser, and survives a broken store", () => {
    const store = memory();
    setGuestDone(["a"], store);
    expect(guestDone(store)).toEqual(["a"]);
    store.setItem("ts.learn.done", "{not json");
    expect(guestDone(store)).toEqual([]);
    expect(guestDone(null)).toEqual([]);
  });

  it("prints only the other names the label does not already spell", () => {
    const eps: Term = {
      id: "eps",
      label: "Beneficio por acción (BPA / EPS)",
      aliases: ["EPS", "bpa", "earnings per share"],
      desc: "",
      lesson: null,
    };
    expect(shownAliases(eps)).toEqual(["earnings per share"]);
    expect(shownAliases({ ...eps, label: "Beta", aliases: ["beta", "β"] })).toEqual([
      "β",
    ]);
  });

  it("toggles one lesson without duplicating it", () => {
    expect(toggled(["a"], "a", true)).toEqual(["a"]);
    expect(toggled(["a", "b"], "a", false)).toEqual(["b"]);
  });
});

describe("Paths", () => {
  it("fills one button per screen: the path the reader is in", () => {
    const html = renderToStaticMarkup(
      <Paths curriculum={curriculum} done={new Set(["c"])} />,
    );
    // The hero is the one filled button; "tax-es" is read to the end.
    expect(html.match(/ag-btn-cta/g)).toHaveLength(1);
    expect(html).toContain("learn.hero_resume");
    expect(html).toContain("learn.review");
    expect(html).toContain("learn.path_done");
  });

  it("scales the bar to the share read rather than sizing it", () => {
    const html = renderToStaticMarkup(
      <Paths curriculum={curriculum} done={new Set(["a"])} />,
    );
    expect(html).toContain("transform:scaleX(0.5)");
    expect(html).not.toMatch(/width:\s*\d/);
    expect(html).toContain('aria-valuenow="1"');
  });
});

describe("LessonBody", () => {
  const progress = { done: new Set<string>(), mark: () => {} };

  it("says where the reader is and offers to mark it read", () => {
    const html = renderToStaticMarkup(
      <LessonBody lesson={lesson} progress={progress} place={{ at: 2, total: 2 }} />,
    );
    expect(html).toContain("learn.lesson_of");
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain("ag-btn-cta");
    expect(html).toContain("tab=risk");
    expect(html).toContain("PER</button>");
    expect(html).toContain("learn.ask");
    expect(html).not.toContain("learn.disclaimer");
  });

  it("drops the filled button once read", () => {
    const html = renderToStaticMarkup(
      <LessonBody lesson={lesson} progress={{ ...progress, done: new Set(["b"]) }} />,
    );
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("lr-mark-on");
    expect(html).not.toContain("ag-btn-cta lr-mark");
  });

  it("closes a read lesson with the way on, and lists the steps to try", () => {
    const html = renderToStaticMarkup(
      <LessonBody
        lesson={{ ...lesson, steps: [{ text: "Open it.", app: "ticker" }] }}
        progress={{ ...progress, done: new Set(["b"]) }}
      />,
    );
    expect(html).toContain("learn.lesson_done");
    expect(html).toContain("learn.try_title");
    expect(html).toContain("Open it.");
    const fresh = renderToStaticMarkup(
      <LessonBody lesson={lesson} progress={progress} />,
    );
    expect(fresh).not.toContain("learn.lesson_done");
    expect(fresh).not.toContain("learn.try_title");
  });

  it("carries the tax disclaimer on the Spanish-tax path only", () => {
    const html = renderToStaticMarkup(
      <LessonBody lesson={{ ...lesson, path: "tax-es" }} progress={progress} />,
    );
    expect(html).toContain("learn.disclaimer");
  });
});

describe("TermList", () => {
  it("marks the term a lesson linked to and links a term to its lesson", () => {
    const html = renderToStaticMarkup(<TermList terms={terms} focus="index" />);
    expect(html).toContain('id="lr-term-index"');
    expect(html).toMatch(/class="lr-term lr-term-on" id="lr-term-index"/);
    expect(html).toContain("lesson=a");
    expect(html).not.toContain("learn.clear");
  });
});

describe("next up", () => {
  it("opens the first unread lesson across the paths, with the minutes left", () => {
    const up = nextUp(curriculum, new Set(["a"]))!;
    expect(up.lesson.id).toBe("b");
    expect([up.at, up.total, up.read, up.all]).toEqual([2, 2, 1, 3]);
    expect([up.minutesLeft, up.minutesAll]).toEqual([9, 12]);
    expect(nextUp(curriculum, new Set(["a", "b", "c"]))).toBeNull();
  });

  it("tells which path teaches a term", () => {
    const paths = lessonPaths(curriculum);
    expect(inPath(terms, "start", paths).map((t) => t.id)).toEqual(["index"]);
    expect(inPath(terms, null, paths)).toHaveLength(2);
  });
});

describe("highlight", () => {
  it("marks what matches, whatever the accents and case", () => {
    expect(highlight("Índice bursátil", "indice")).toEqual([
      { text: "Índice", hit: true },
      { text: " bursátil", hit: false },
    ]);
    expect(highlight("P/E ratio", "p/e")[0]).toEqual({ text: "P/E", hit: true });
    expect(highlight("abc", "")).toEqual([{ text: "abc", hit: false }]);
    expect(highlight("abc", "x")).toEqual([{ text: "abc", hit: false }]);
  });
});

describe("Quiz", () => {
  it("offers every option and explains nothing until one is pressed", () => {
    const html = renderToStaticMarkup(
      <Quiz
        quiz={{ question: "Q?", options: ["x", "y"], answer: 1, why: "Because." }}
      />,
    );
    expect(html).toContain("Q?");
    expect(html.match(/class="lr-opt"/g)).toHaveLength(2);
    expect(html).not.toContain("Because.");
  });
});

describe("blocks", () => {
  it("sets the opening line apart and gives a three-section lesson its cards", () => {
    const out = blocks("Intro.\n\n## Idea\n\nA\n\n## Example\n\nB\n\n## Mistake\n\nC");
    expect(out.intro).toBe("Intro.");
    expect(out.blocks.map((b) => b.role)).toEqual(["idea", "example", "error"]);
  });

  it("draws any other shape as it was written", () => {
    const out = blocks("## One\n\nA\n\n## Two\n\nB");
    expect(out.intro).toBe("");
    expect(out.blocks.map((b) => b.role)).toEqual(["plain", "plain"]);
  });
});

describe("termOfDay", () => {
  const taught = (id: string, lesson: boolean): Term =>
    ({
      id,
      label: id,
      aliases: [],
      desc: "",
      lesson: lesson ? { id: "x", title: "X", minutes: 1 } : null,
    }) as Term;
  const list = [taught("a", true), taught("b", false), taught("c", true)];

  it("steps through the taught terms by the calendar, the same all day", () => {
    const one = termOfDay(list, new Date(2026, 10, 26, 8))!;
    expect(termOfDay(list, new Date(2026, 10, 26, 23))).toEqual(one);
    expect(termOfDay(list, new Date(2026, 10, 27))!.id).not.toBe(one.id);
    expect(["a", "c"]).toContain(one.id);
  });

  it("has none when no lesson teaches any", () => {
    expect(termOfDay([taught("b", false)], new Date())).toBeNull();
  });
});

describe("live figures", () => {
  const quote = { ticker: "NVDA", price: 100, currency: "USD" } as never;
  const metrics = {
    kpis: [
      { key: "market_cap", value: 1, formatted: "4,2 B $" },
      { key: "pe_ttm", value: null, formatted: "n/a" },
    ],
  } as never;

  it("reads the price and the limit two per cent below it", () => {
    expect(figure("price", { quote, metrics: null }, "en")).toContain("100");
    expect(figure("limit", { quote, metrics: null }, "en")).toContain("98");
  });

  it("leaves out a figure that is missing rather than guess", () => {
    expect(figure("cap", { quote, metrics }, "en")).toBe("4,2 B $");
    expect(figure("pe", { quote, metrics }, "en")).toBeNull();
    expect(figure("price", { quote: null, metrics: null }, "en")).toBeNull();
  });
});
