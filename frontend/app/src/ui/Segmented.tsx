/**
 * The segmented control: a few mutually exclusive options in one track — a
 * chart's range, a table's span, a page's view.
 *
 * Five pages drew one each, with four ways of saying "this one is on" (a grey
 * fill, the CTA fill, a purple fill, a pill) on three radii. This is the one;
 * `ui.css` styles it and a page only places it.
 *
 * The open option sits on a thumb that slides to the option picked, as the
 * tab strip's underline does: the eye follows one plate moving instead of one
 * fill vanishing and another appearing. The buttons stay toggle buttons
 * (`aria-pressed`) in a labelled group, so each is its own stop in the tab
 * order and a press is the only thing that changes the value.
 */

import { type ReactNode, useEffect, useLayoutEffect, useRef } from "react";

import "./ui.css";

export type SegItem<T extends string> = { id: T; label: ReactNode };

/**
 * Lay the thumb under the pressed option, as `--seg-*` on the track. The
 * first placement does not animate (`data-glide` comes a frame later), so a
 * page opens with the thumb already in place; no option pressed hides it.
 */
function useThumb<T extends HTMLElement>(value: string) {
  const track = useRef<T>(null);

  const place = () => {
    const row = track.current;
    if (!row) return;
    const on = row.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!on) {
      delete row.dataset.thumb;
      return;
    }
    row.style.setProperty("--seg-x", `${on.offsetLeft}px`);
    row.style.setProperty("--seg-y", `${on.offsetTop}px`);
    row.style.setProperty("--seg-w", `${on.offsetWidth}px`);
    row.style.setProperty("--seg-h", `${on.offsetHeight}px`);
    row.dataset.thumb = "";
    if (!row.dataset.glide) requestAnimationFrame(() => (row.dataset.glide = ""));
  };

  useLayoutEffect(place, [value]);

  useEffect(() => {
    const row = track.current;
    if (!row) return;
    // A wrap, a phone's full-width row or the fonts arriving resize the
    // options under a thumb placed before.
    const watch = new ResizeObserver(place);
    watch.observe(row);
    row.querySelectorAll("button").forEach((option) => watch.observe(option));
    void document.fonts?.ready.then(place);
    return () => watch.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return track;
}

export function Segmented<T extends string>({
  items,
  value,
  onPick,
  label,
  className,
}: {
  items: readonly SegItem<T>[];
  value: T;
  onPick: (next: T) => void;
  /** Names the group for assistive tech. */
  label: string;
  /** Layout only — where the page places the track, never its look. */
  className?: string;
}) {
  const track = useThumb<HTMLDivElement>(value);
  return (
    <div
      className={className ? `ag-seg ${className}` : "ag-seg"}
      role="group"
      aria-label={label}
      ref={track}
    >
      <span className="ag-seg-thumb" aria-hidden="true" />
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="ag-seg-opt"
          aria-pressed={item.id === value}
          onClick={() => onPick(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
