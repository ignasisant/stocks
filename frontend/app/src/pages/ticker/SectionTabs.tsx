/**
 * The page's index: a strip of section names that stays at the top while the
 * page scrolls under it, marks the section being read, and jumps to another.
 *
 * A company page is a dozen cards long; without it a reader after the
 * analysts scrolls past the chart, the valuation and the results to find
 * them, and back up again to see the price. Once the header has scrolled
 * away the strip also carries the price, so the figure the page is about is
 * never more than a glance away.
 *
 * Links, not tabs: every section stays on the page, so a find-in-page, a
 * shared `#tk-s-…` and a screen reader's heading list all still work. The
 * one marked is `aria-current="location"`.
 *
 * A jump is instant. A smooth scroll across ten cards that are still
 * loading lands short of a target the skeletons above it keep pushing down;
 * instead the target is pinned under the strip for a moment while those
 * cards settle, until the reader touches the page themselves.
 */

import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { useT } from "../../shell/i18n";
import { useTabStrip } from "../../shell/useTabStrip";
import { LAND_EVENT } from "../../ui/Fold";

export type SectionKey =
  | "summary"
  | "price"
  | "valuation"
  | "business"
  | "opinions"
  | "fund"
  | "market"
  | "compare";

export const sectionId = (key: SectionKey) => `tk-s-${key}`;

/** Fewer than this and the page is short enough to read without an index. */
const MIN_SECTIONS = 3;

/** How long a jump keeps its target pinned while the cards above it settle. */
const HOLD_MS = 1500;

/** How long a page opened on a section's link waits for that section. */
const LAND_WAIT_MS = 8000;

/**
 * Scroll a section under the strip, and keep it there while the page above
 * it is still changing height. A wheel, a touch or a key ends the hold: the
 * reader has taken over.
 */
export function jumpTo(key: SectionKey): void {
  const target = document.getElementById(sectionId(key));
  if (!target) return;
  // A phone's folds under the heading open first (`ui/Fold`), so the hold
  // below keeps the target in place while they grow.
  dispatchEvent(new CustomEvent(LAND_EVENT, { detail: sectionId(key) }));
  const place = () => target.scrollIntoView({ block: "start", behavior: "instant" });
  place();
  if (location.hash !== `#${target.id}`) {
    history.replaceState(history.state, "", `#${target.id}`);
  }
  const until = performance.now() + HOLD_MS;
  let frame = 0;
  const stop = () => {
    cancelAnimationFrame(frame);
    for (const kind of ["wheel", "touchstart", "keydown", "pointerdown"]) {
      removeEventListener(kind, stop);
    }
  };
  for (const kind of ["wheel", "touchstart", "keydown", "pointerdown"]) {
    addEventListener(kind, stop, { passive: true, once: true });
  }
  // Re-placed when the target moves, and when the page grows: a section near
  // the foot lands short while the lazy cards below it are still skeletons,
  // and stays short unless it is put back once there is room to scroll.
  const page = document.documentElement;
  let top = target.getBoundingClientRect().top;
  let tall = page.scrollHeight;
  const hold = () => {
    const now = target.getBoundingClientRect().top;
    if (Math.abs(now - top) > 1 || page.scrollHeight !== tall) {
      place();
      top = target.getBoundingClientRect().top;
      tall = page.scrollHeight;
    }
    if (performance.now() < until) frame = requestAnimationFrame(hold);
    else stop();
  };
  frame = requestAnimationFrame(hold);
}

export function SectionTabs({
  sections,
  head,
  mini,
}: {
  sections: { key: SectionKey; label: string }[];
  /** The page header: once it has scrolled away the strip shows `mini`. */
  head: RefObject<HTMLElement | null>;
  /** The symbol and its price, for when the header is out of sight. */
  mini: ReactNode;
}) {
  const t = useT();
  const [current, setCurrent] = useState<SectionKey>(sections[0]?.key ?? "price");
  const [stuck, setStuck] = useState(false);
  const bar = useRef<HTMLDivElement>(null);
  const strip = useTabStrip<HTMLElement>(current);
  const keys = sections.map((one) => one.key).join(",");
  const landed = useRef(false);

  // A shared `#tk-s-…` link: the browser looks for the anchor at first paint,
  // before the section exists, and gives up. Land on it once it is drawn.
  useEffect(() => {
    if (landed.current) return;
    const key = sections.find((one) => `#${sectionId(one.key)}` === location.hash)?.key;
    if (!key) return;
    const until = performance.now() + LAND_WAIT_MS;
    let frame = 0;
    // A reader who scrolls while the page loads has chosen where to be.
    const quit = () => {
      landed.current = true;
      cancelAnimationFrame(frame);
    };
    const kinds = ["wheel", "touchstart", "keydown", "pointerdown"];
    for (const kind of kinds)
      addEventListener(kind, quit, { passive: true, once: true });
    const look = () => {
      if (landed.current) return;
      if (document.getElementById(sectionId(key))) {
        landed.current = true;
        jumpTo(key);
      } else if (performance.now() < until) {
        frame = requestAnimationFrame(look);
      }
    };
    frame = requestAnimationFrame(look);
    return () => {
      cancelAnimationFrame(frame);
      for (const kind of kinds) removeEventListener(kind, quit);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys]);

  useEffect(() => {
    let frame = 0;
    const read = () => {
      frame = 0;
      const box = bar.current?.getBoundingClientRect();
      const floor = box?.bottom ?? 0;
      // Stuck: the strip is pinned at its `top` and the header has gone
      // under it. At the top of the page the strip sits just below the
      // header, so the header's foot alone says nothing.
      const pin = bar.current ? parseFloat(getComputedStyle(bar.current).top) || 0 : 0;
      setStuck(
        !!box &&
          box.top <= pin + 1 &&
          (head.current?.getBoundingClientRect().bottom ?? 1) <= floor,
      );
      // The last section whose top has reached the strip is the one in view;
      // at the foot of the page it is the last one, however short.
      let on = sections[0]?.key;
      for (const one of sections) {
        const el = document.getElementById(sectionId(one.key));
        if (el && el.getBoundingClientRect().top <= floor + 24) on = one.key;
      }
      const end = innerHeight + scrollY >= document.documentElement.scrollHeight - 4;
      if (end && sections.length) on = sections[sections.length - 1]!.key;
      if (on) setCurrent(on);
    };
    const queue = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    read();
    addEventListener("scroll", queue, { passive: true });
    addEventListener("resize", queue);
    return () => {
      cancelAnimationFrame(frame);
      removeEventListener("scroll", queue);
      removeEventListener("resize", queue);
    };
    // `sections` is rebuilt every render; its keys are what matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, head]);

  if (sections.length < MIN_SECTIONS) return null;
  return (
    <div ref={bar} className="tk-tabs" data-stuck={stuck ? "" : undefined}>
      {stuck ? <div className="tk-tabs-mini">{mini}</div> : null}
      <nav
        ref={strip}
        className="ag-tabs ag-fade-x tk-tabs-strip"
        aria-label={t("ticker.sections")}
      >
        {sections.map((one) => (
          <a
            key={one.key}
            href={`#${sectionId(one.key)}`}
            className={
              one.key === current ? "ag-tab ag-tab-on tk-tab" : "ag-tab tk-tab"
            }
            aria-current={one.key === current ? "location" : undefined}
            onClick={(event) => {
              event.preventDefault();
              setCurrent(one.key);
              jumpTo(one.key);
            }}
          >
            {one.label}
          </a>
        ))}
        <span className="ag-tabs-ink" aria-hidden="true" />
      </nav>
    </div>
  );
}
