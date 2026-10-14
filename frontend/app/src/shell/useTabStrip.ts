/**
 * A row of tabs that scrolls sideways on a phone: keeps the open tab in the
 * middle and tells the stylesheet which edges still have tabs past them
 * (`data-more="start" | "end" | "both"`), which `.ag-fade-x` draws as a fade.
 *
 * The open tab is centred so the one before and the one after are both in
 * view, each a tap away. Only the strip scrolls: `scrollIntoView` would also
 * move the page under the reader. The strip must be the tabs' offset parent
 * (`position: relative`). Where every tab fits there is nothing to scroll and
 * this does nothing.
 *
 * It also lays the strip's underline (`.ag-tabs-ink`, `ui/Tabs.tsx`) under the
 * open tab, as `--ink-x` / `--ink-w` on the strip: one mark that travels from
 * the tab left to the tab picked, so the eye follows the move instead of
 * seeing one line vanish and another appear. `data-ink` is set only after the
 * first placement, so the page opens with the line already in place rather
 * than sliding in from the left edge.
 */

import { useEffect, useLayoutEffect, useRef } from "react";

export function useTabStrip<T extends HTMLElement = HTMLDivElement>(active: string) {
  const strip = useRef<T>(null);
  // The first centring is instant — the page opened on that tab, nothing moved.
  const moved = useRef(false);

  const centre = (smooth: boolean) => {
    const row = strip.current;
    const on = row?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!row || !on) return;
    row.style.setProperty("--ink-x", `${on.offsetLeft}px`);
    row.style.setProperty("--ink-w", `${on.offsetWidth}`);
    if (!row.dataset.ink) requestAnimationFrame(() => (row.dataset.ink = ""));
    const left = on.offsetLeft - (row.clientWidth - on.offsetWidth) / 2;
    row.scrollTo({ left, behavior: smooth ? "smooth" : "auto" });
  };

  useLayoutEffect(() => {
    centre(moved.current);
    moved.current = true;
  }, [active]);

  useEffect(() => {
    const row = strip.current;
    if (!row) return;
    const mark = () => {
      const start = row.scrollLeft > 1;
      const end = row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      if (start && end) row.dataset.more = "both";
      else if (start) row.dataset.more = "start";
      else if (end) row.dataset.more = "end";
      else delete row.dataset.more;
    };
    mark();
    row.addEventListener("scroll", mark, { passive: true });
    // A rotation, or the faces arriving and widening the tabs, moves the open
    // tab off-centre: put it back, and re-read the edges.
    const watch = new ResizeObserver(() => {
      centre(false);
      mark();
    });
    watch.observe(row);
    // A tab's count arriving widens it under a line placed before it came.
    row.querySelectorAll('[role="tab"]').forEach((tab) => watch.observe(tab));
    void document.fonts?.ready.then(() => {
      centre(false);
      mark();
    });
    return () => {
      row.removeEventListener("scroll", mark);
      watch.disconnect();
    };
  }, []);

  return strip;
}
