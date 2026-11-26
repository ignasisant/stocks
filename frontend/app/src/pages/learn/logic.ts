/**
 * The Learn page's pure parts: where a path stands, which lesson to open
 * next, which terms a search matches, and a guest's ticks in the browser.
 */

import type { Curriculum, LearnPath, LessonRef, Term } from "./types";

/** `learn.path_<id>_title`'s id part: catalog keys take no hyphens. */
export const pathKey = (id: string) => id.replace(/-/g, "_");

export type Standing = { read: number; total: number; next: string | null };

/** How far into `path` the reader is, and the first lesson still unread. */
export function standing(path: LearnPath, done: ReadonlySet<string>): Standing {
  const read = path.lessons.filter((lesson) => done.has(lesson.id)).length;
  const next = path.lessons.find((lesson) => !done.has(lesson.id))?.id ?? null;
  return { read, total: path.lessons.length, next };
}

/** "portfolio?tab=risk" as a Link's page and params. */
export function appTarget(
  app: string,
): { page: string; params?: Record<string, string> } | null {
  if (!app) return null;
  const [page, query] = app.split("?", 2);
  if (!page) return null;
  if (!query) return { page };
  return { page, params: Object.fromEntries(new URLSearchParams(query)) };
}

/** Folded for matching: case and accents ignored, so "indice" finds "Índice". */
export function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

/** The terms whose label or an alias contains `query`; the label matches first. */
export function matching(terms: readonly Term[], query: string): Term[] {
  const q = fold(query);
  if (!q) return [...terms];
  const byLabel: Term[] = [];
  const byOther: Term[] = [];
  for (const term of terms) {
    if (fold(term.label).includes(q)) byLabel.push(term);
    else if (term.aliases.some((alias) => fold(alias).includes(q))) byOther.push(term);
    else if (fold(term.desc).includes(q)) byOther.push(term);
  }
  return [...byLabel, ...byOther];
}

/** A guest's read lessons: kept in this browser, because the demo's prefs are
    shared and one visitor's ticks are not another's. Storage can be missing
    or refuse (private windows); the page then simply forgets. */
const GUEST_KEY = "ts.learn.done";

export function guestDone(storage?: Storage | null): string[] {
  try {
    const raw = (storage ?? window.localStorage).getItem(GUEST_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function setGuestDone(ids: readonly string[], storage?: Storage | null): void {
  try {
    (storage ?? window.localStorage).setItem(GUEST_KEY, JSON.stringify(ids));
  } catch {
    // Nothing to do: the tick holds for this visit only.
  }
}

/** `done` with `id` added or taken out, order kept. */
export function toggled(done: readonly string[], id: string, on: boolean): string[] {
  const rest = done.filter((value) => value !== id);
  return on ? [...rest, id] : rest;
}

/**
 * The other names worth printing beside a label: one the label already
 * spells ("Beta" beside "Beta", "EPS" beside "BPA / EPS") is noise. Search
 * still reads them all.
 */
export function shownAliases(term: Term): string[] {
  const words = new Set(fold(term.label).split(/[^\p{L}\p{N}]+/u));
  const label = fold(term.label);
  return term.aliases.filter((alias) => {
    const a = fold(alias);
    return a !== label && !words.has(a);
  });
}

/** Where a lesson sits in its path: the 1-based position and the path's length. */
export type Place = { at: number; total: number };

export function place(curriculum: Curriculum, lesson: string): Place | null {
  for (const path of curriculum.paths) {
    const at = path.lessons.findIndex((ref) => ref.id === lesson);
    if (at >= 0) return { at: at + 1, total: path.lessons.length };
  }
  return null;
}

/** The lesson to open next: the first unread one in path order, where it sits
    in its path, and the minutes left across every path (and in all of them). */
export type NextUp = {
  path: LearnPath;
  lesson: LessonRef;
  at: number;
  total: number;
  read: number;
  all: number;
  minutesLeft: number;
  minutesAll: number;
};

export function nextUp(
  curriculum: Curriculum,
  done: ReadonlySet<string>,
): NextUp | null {
  const lessons = curriculum.paths.flatMap((path) => path.lessons);
  const open = curriculum.paths.find((path) =>
    path.lessons.some((x) => !done.has(x.id)),
  );
  if (!open) return null;
  const lesson = open.lessons.find((x) => !done.has(x.id))!;
  const minutes = (list: readonly LessonRef[]) =>
    list.reduce((sum, x) => sum + x.minutes, 0);
  return {
    path: open,
    lesson,
    at: open.lessons.indexOf(lesson) + 1,
    total: open.lessons.length,
    read: lessons.filter((x) => done.has(x.id)).length,
    all: lessons.length,
    minutesLeft: minutes(lessons.filter((x) => !done.has(x.id))),
    minutesAll: minutes(lessons),
  };
}

/** Lesson id → the id of the path that holds it. */
export function lessonPaths(curriculum: Curriculum): Record<string, string> {
  const out: Record<string, string> = {};
  for (const path of curriculum.paths)
    for (const lesson of path.lessons) out[lesson.id] = path.id;
  return out;
}

/** The glossary's terms taught on `path`; null is every term. */
export function inPath(
  terms: readonly Term[],
  path: string | null,
  paths: Readonly<Record<string, string>>,
): Term[] {
  if (!path) return [...terms];
  return terms.filter((term) => term.lesson && paths[term.lesson.id] === path);
}

export type Piece = { text: string; hit: boolean };

/** `text` cut where `query` occurs, case and accents ignored, so a match can
    be drawn marked. An empty query is the whole text, unmarked. */
export function highlight(text: string, query: string): Piece[] {
  const q = fold(query);
  if (!q) return [{ text, hit: false }];
  let folded = "";
  const starts: number[] = [];
  const ends: number[] = [];
  let at = 0;
  for (const char of text) {
    const part = char.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
    for (let i = 0; i < part.length; i++) {
      starts.push(at);
      ends.push(at + char.length);
    }
    folded += part;
    at += char.length;
  }
  const pieces: Piece[] = [];
  let from = 0;
  let found = folded.indexOf(q);
  while (found >= 0) {
    const start = starts[found]!;
    const end = ends[found + q.length - 1]!;
    if (start >= from) {
      if (start > from) pieces.push({ text: text.slice(from, start), hit: false });
      pieces.push({ text: text.slice(start, end), hit: true });
      from = end;
    }
    found = folded.indexOf(q, found + q.length);
  }
  if (from < text.length) pieces.push({ text: text.slice(from), hit: false });
  return pieces;
}

export type Block = { role: "idea" | "example" | "error" | "plain"; text: string };

/**
 * A lesson body as the blocks it is drawn in: the opening line to say apart,
 * then, when the lesson follows the house shape of three `##` sections (the
 * idea, an example, the typical mistake), each in its own card. Any other
 * shape is drawn as one plain run, as it was written.
 */
export function blocks(body: string): { intro: string; blocks: Block[] } {
  const parts = body.split(/^(?=## )/m);
  const intro = parts[0]?.startsWith("## ") ? "" : (parts.shift() ?? "").trim();
  const roles: Block["role"][] = parts.length === 3 ? ["idea", "example", "error"] : [];
  return {
    intro,
    blocks: parts.map((text, at) => ({
      role: roles[at] ?? "plain",
      text: text.trim(),
    })),
  };
}

/**
 * One term a day, the same for every reader and every visit that day: the
 * terms a lesson teaches, in glossary order, stepped through by the calendar.
 */
export function termOfDay(terms: readonly Term[], day: Date): Term | null {
  const taught = terms.filter((term) => term.lesson !== null);
  if (taught.length === 0) return null;
  const days = Math.floor(
    Date.UTC(day.getFullYear(), day.getMonth(), day.getDate()) / 86_400_000,
  );
  return taught[days % taught.length] ?? null;
}
