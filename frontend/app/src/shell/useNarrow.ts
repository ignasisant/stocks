/**
 * Whether the main column is at its narrow width — the 40rem the shell's
 * phone layout starts at, measured on `#ag-main` so an open chat drawer
 * narrows a page the way a phone does.
 *
 * The same test as `@container ag-main (max-width: 40rem)` in CSS, answered
 * in JS so a component can mount one rendering rather than both. A table
 * that ships its grid and its phone rendering and hides one with CSS still
 * builds both trees — two sets of rows, two sets of ticker cells each asking
 * for a logo — on every page with a table. One store for the whole app: one
 * ResizeObserver on the column, every subscriber told on a change.
 *
 * The content box, as a size container is measured; `rem` against the root
 * font size, as it is in a container query. Wide until the column exists —
 * a render without layout (a test, the server).
 */

import { useSyncExternalStore } from "react";
import { MAIN_ID } from "./Layout";

const NARROW_REM = 40;

let narrow = false;
let measured = false;
const listeners = new Set<() => void>();
let watcher: ResizeObserver | null = null;
let unwatch: (() => void) | null = null;

function column(): HTMLElement | null {
  return typeof document === "undefined" ? null : document.getElementById(MAIN_ID);
}

function limit(): number {
  const root = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return NARROW_REM * (Number.isFinite(root) && root > 0 ? root : 16);
}

function content(el: HTMLElement): number {
  const style = getComputedStyle(el);
  return (
    el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
  );
}

function settle(width: number): void {
  const next = width <= limit();
  measured = true;
  if (next === narrow) return;
  narrow = next;
  for (const tell of listeners) tell();
}

function measure(): void {
  const el = column();
  if (el) settle(content(el));
}

function watch(): void {
  const el = column();
  if (!el) return;
  settle(content(el));
  if (typeof ResizeObserver === "function") {
    watcher = new ResizeObserver(([entry]) => {
      if (entry) settle(entry.contentRect.width);
    });
    watcher.observe(el);
    return;
  }
  window.addEventListener("resize", measure);
  unwatch = () => window.removeEventListener("resize", measure);
}

function subscribe(tell: () => void): () => void {
  listeners.add(tell);
  if (listeners.size === 1) watch();
  return () => {
    listeners.delete(tell);
    if (listeners.size > 0) return;
    watcher?.disconnect();
    watcher = null;
    unwatch?.();
    unwatch = null;
    measured = false;
  };
}

function snapshot(): boolean {
  // The first render, before anyone subscribed: measured here so the tree
  // mounts the rendering the column calls for rather than the wide one and
  // then swapping. Once, until the last subscriber leaves.
  if (!measured) measure();
  return narrow;
}

const wide = () => false;

export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, snapshot, wide);
}
