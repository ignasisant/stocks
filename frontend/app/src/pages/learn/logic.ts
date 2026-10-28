/**
 * The Learn page's pure parts: where a path stands, which lesson to open
 * next, which terms a search matches, and a guest's ticks in the browser.
 */

import type { Curriculum, LearnPath, Term } from "./types";

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
