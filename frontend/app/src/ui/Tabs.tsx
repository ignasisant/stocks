/**
 * The one tab strip every page uses: Portfolio, Today, Profile, Sentiment.
 *
 * A single row with an underline that travels to the tab picked
 * (`useTabStrip` places it). Where the row is wider than the page it scrolls
 * sideways, keeps the open tab centred and fades the edge with more tabs past
 * it. The keyboard follows the WAI-ARIA tabs pattern with manual activation:
 * the arrows, Home and End move focus along the strip and Enter or Space opens
 * the tab. Moving focus alone does not open it, because opening a portfolio tab
 * fetches its data, and arrowing past five tabs should not start five loads.
 */

import type { KeyboardEvent, ReactNode } from "react";

import { useTabStrip } from "../shell/useTabStrip";
import "./ui.css";

export type TabItem<T extends string> = {
  id: T;
  label: ReactNode;
  /** A count shown beside the label; nothing is drawn for 0 or none. */
  count?: number | null;
};

const STEP: Record<string, (at: number, n: number) => number> = {
  ArrowRight: (at, n) => (at + 1) % n,
  ArrowLeft: (at, n) => (at - 1 + n) % n,
  Home: () => 0,
  End: (_, n) => n - 1,
};

/** Where `key` moves focus from tab `at` of `n`, or null for any other key.
    The arrows wrap round the ends, as the ARIA pattern has them. */
export function stepTo(key: string, at: number, n: number): number | null {
  const step = STEP[key];
  return step ? step(at, n) : null;
}

export function Tabs<T extends string>({
  items,
  active,
  onPick,
  label,
  className,
}: {
  items: readonly TabItem<T>[];
  active: T;
  onPick: (tab: T) => void;
  label?: string;
  className?: string;
}) {
  const strip = useTabStrip(active);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    const at = tabs.indexOf(document.activeElement as HTMLButtonElement);
    const to = at < 0 ? null : stepTo(event.key, at, tabs.length);
    if (to === null) return;
    event.preventDefault();
    const next = tabs[to];
    next?.focus();
    next?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  return (
    <div
      className={className ? `ag-tabs ag-fade-x ${className}` : "ag-tabs ag-fade-x"}
      role="tablist"
      aria-label={label}
      ref={strip}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={item.id === active}
          // One stop in the page's tab order; the arrows move within the strip.
          tabIndex={item.id === active ? 0 : -1}
          className={item.id === active ? "ag-tab ag-tab-on" : "ag-tab"}
          onClick={() => onPick(item.id)}
        >
          {item.label}
          {item.count ? <span className="ag-tab-n">{item.count}</span> : null}
        </button>
      ))}
      <span className="ag-tabs-ink" aria-hidden="true" />
    </div>
  );
}
