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
import { LessonBody } from "./Lesson";
import {
  appTarget,
  fold,
  guestDone,
  matching,
  pathKey,
  place,
  shownAliases,
  setGuestDone,
  standing,
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
    // "start" has unread lessons and nothing read; "tax-es" is read to the end.
    expect(html.match(/ag-btn-cta/g)).toHaveLength(1);
    expect(html).toContain("learn.start");
    expect(html).toContain("learn.review");
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
    expect(html).toContain("term=pe");
    expect(html).not.toContain("learn.disclaimer");
  });

  it("drops the filled button once read", () => {
    const html = renderToStaticMarkup(
      <LessonBody lesson={lesson} progress={{ ...progress, done: new Set(["b"]) }} />,
    );
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("ag-btn-cta");
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
