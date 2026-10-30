/**
 * Pull down from the top of a page to ask for its figures again — in the
 * Home Screen app only.
 *
 * Safari draws this gesture itself; an app opened from the Home Screen has no
 * browser chrome, so the same pull there only bounced. A tab keeps Safari's
 * (which reloads the whole document), so this one stays out of its way.
 *
 * It reloads in place (`shell/resume`): the figures stay up and dim, and the
 * strip at the top says it is working until the last answer lands. A pull
 * that starts inside something that scrolls on its own — a table scrolled
 * down, a sheet — is that thing's, not the page's.
 */

import { useEffect, useRef, useState } from "react";
import { useT } from "./i18n";
import { MAIN_ID } from "./Layout";
import { isStandalone, reloadAll } from "./resume";
import { Status } from "../ui/Status";

/** How far the strip travels for the finger's distance: a pull is damped. */
const DAMP = 0.5;
/** Pulled this far (after damping) and letting go reloads. */
const TRIGGER_PX = 64;
const MAX_PX = 96;
/** The strip never outstays this, whatever is still out. */
const CAP_MS = 20_000;

/** Whether a pull starting at `target` belongs to the page. */
function pullsPage(target: EventTarget | null): boolean {
  if (window.scrollY > 0 || !(target instanceof Element)) return false;
  const main = document.getElementById(MAIN_ID);
  if (!main || !main.contains(target)) return false;
  if (target.closest("input, textarea, select, [role='dialog'], [role='slider']"))
    return false;
  for (
    let node: Element | null = target;
    node && node !== main;
    node = node.parentElement
  ) {
    if (node.scrollTop > 0) return false;
  }
  return true;
}

export function PullRefresh() {
  const t = useT();
  const [on] = useState(
    () => isStandalone() && !!window.matchMedia?.("(pointer: coarse)").matches,
  );
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  useEffect(() => {
    if (!on) return;
    let start: { x: number; y: number } | null = null;
    let distance = 0;
    const begin = (event: TouchEvent) => {
      const touch = event.touches[0];
      start =
        !busyRef.current &&
        event.touches.length === 1 &&
        touch &&
        pullsPage(event.target)
          ? { x: touch.clientX, y: touch.clientY }
          : null;
      distance = 0;
    };
    const move = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!start || !touch) return;
      const dx = touch.clientX - start.x;
      const dy = touch.clientY - start.y;
      // Sideways first, or up: a swipe or a scroll, not a pull.
      if (dy <= 0 || (distance === 0 && Math.abs(dx) > dy)) {
        start = null;
        setPull(0);
        return;
      }
      distance = Math.min(dy * DAMP, MAX_PX);
      setPull(distance);
    };
    const end = () => {
      const pulled = start !== null && distance >= TRIGGER_PX;
      start = null;
      distance = 0;
      setPull(0);
      if (!pulled) return;
      busyRef.current = true;
      setBusy(true);
      const cap = new Promise<void>((resolve) => setTimeout(resolve, CAP_MS));
      void Promise.race([reloadAll(), cap]).finally(() => {
        busyRef.current = false;
        setBusy(false);
      });
    };
    document.addEventListener("touchstart", begin, { passive: true });
    document.addEventListener("touchmove", move, { passive: true });
    document.addEventListener("touchend", end);
    document.addEventListener("touchcancel", end);
    return () => {
      document.removeEventListener("touchstart", begin);
      document.removeEventListener("touchmove", move);
      document.removeEventListener("touchend", end);
      document.removeEventListener("touchcancel", end);
    };
  }, [on]);

  if (!on || (!busy && pull === 0)) return null;
  const ready = pull >= TRIGGER_PX;
  return (
    <div
      className="ag-pull"
      data-ready={ready || busy || undefined}
      style={
        busy ? undefined : { transform: `translate(-50%, ${pull - TRIGGER_PX}px)` }
      }
    >
      {busy ? (
        <Status label={t("common.pull_busy")} />
      ) : (
        <div className="ag-work" aria-hidden="true">
          <span
            className="ag-pull-glyph"
            style={{ transform: `rotate(${(pull / TRIGGER_PX) * 180}deg)` }}
          >
            ✻
          </span>
          {t(ready ? "common.pull_release" : "common.pull_refresh")}
        </div>
      )}
    </div>
  );
}
