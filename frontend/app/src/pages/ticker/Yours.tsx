/**
 * The reader's own marks on this name, in one line under the price: the
 * nearest price alert, the buy zone, the nearest exit rule while it is held,
 * and how many of their entry criteria it meets — each with how far the price
 * is from it, each opening its editor.
 *
 * They were three menus and a card away: an alert set last month was not on
 * the screen that shows the price it waits for. Nothing is drawn for a reader
 * who set nothing.
 */

import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { DASH, money, percent } from "../../shell/format";
import { buyRule, liveRule, type JournalEntry } from "../../ui/Journal";
import type { Mine } from "./Actions";
import { getEntryFit } from "./data";
import type { AlertRule } from "./types";

type Tone = "up" | "down" | null;

/** One mark: what it says, how far the price is from it, where it opens. */
export type Mark = {
  kind: "alert" | "buy" | "exit";
  key: string;
  vars: Record<string, string | number>;
  /** The price's distance to the level, a fraction; null when not a price. */
  gap: number | null;
  tone: Tone;
};

/** A rule's level when it is a price; null for every other kind of rule. */
function priceLevel(entry: JournalEntry): number | null {
  const level = entry.snapshot.level;
  return typeof level === "number" && Number.isFinite(level) && level > 0
    ? level
    : null;
}

/** The entry whose level the price is closest to, by distance as a fraction. */
function nearest<T>(items: T[], level: (one: T) => number, price: number): T | null {
  let best: T | null = null;
  for (const one of items) {
    if (!best || Math.abs(level(one) / price - 1) < Math.abs(level(best) / price - 1))
      best = one;
  }
  return best;
}

/**
 * The marks to draw, in reading order. A price alert or a price rule names
 * its level and the distance to it; rules that are not a price (a margin, the
 * thesis) are only counted, and only when nothing priced stands in for them.
 */
export function marks(
  rules: AlertRule[],
  entries: JournalEntry[],
  price: number | null,
  held: boolean,
): Mark[] {
  const out: Mark[] = [];
  const level = (value: number) => money(value, { digits: 2 }) ?? DASH;
  const gap = (value: number) => (price ? value / price - 1 : null);

  const priced = rules.filter(
    (one): one is AlertRule & { price: number } =>
      (one.type === "above" || one.type === "below") &&
      typeof one.price === "number" &&
      one.price > 0,
  );
  const alert = price
    ? nearest(priced, (one) => one.price, price)
    : (priced[0] ?? null);
  if (alert) {
    out.push({
      kind: "alert",
      key: `ticker.mine_alert_${alert.type}`,
      vars: { level: level(alert.price) },
      gap: gap(alert.price),
      tone: null,
    });
  } else if (rules.length) {
    out.push({
      kind: "alert",
      key: rules.length === 1 ? "ticker.mine_alerts_one" : "ticker.mine_alerts_n",
      vars: { n: rules.length },
      gap: null,
      tone: null,
    });
  }

  const live = entries.filter(liveRule);
  const zones = live.filter(
    (one) => buyRule(one) && one.snapshot.rule === "buy_below" && priceLevel(one),
  );
  const zone = nearest(zones, (one) => priceLevel(one) ?? 0, price ?? 1);
  if (zone) {
    const at = priceLevel(zone) ?? 0;
    const inside = zone.state === "hit" || (price !== null && price <= at);
    out.push({
      kind: "buy",
      key: inside ? "ticker.mine_buy_in" : "ticker.mine_buy",
      vars: { level: level(at) },
      gap: inside ? null : gap(at),
      tone: inside ? "up" : null,
    });
  }

  // An exit rule is about a position: on a name not held it waits, unread.
  if (held) {
    const exits = live.filter((one) => !buyRule(one));
    const hit = exits.find((one) => one.state === "hit");
    const floors = exits.filter(
      (one) => one.snapshot.rule === "below" && priceLevel(one),
    );
    const floor = nearest(floors, (one) => priceLevel(one) ?? 0, price ?? 1);
    if (hit) {
      out.push({
        kind: "exit",
        key: "ticker.mine_exit_hit",
        vars: {},
        gap: null,
        tone: "down",
      });
    } else if (floor) {
      const at = priceLevel(floor) ?? 0;
      out.push({
        kind: "exit",
        key: "ticker.mine_exit",
        vars: { level: level(at) },
        gap: gap(at),
        tone: null,
      });
    } else if (exits.length) {
      out.push({
        kind: "exit",
        key: exits.length === 1 ? "ticker.mine_exits_one" : "ticker.mine_exits_n",
        vars: { n: exits.length },
        gap: null,
        tone: null,
      });
    }
  }
  return out;
}

export function Yours({
  ticker,
  mine,
  price,
  held,
  entry: withEntry = true,
}: {
  ticker: string;
  mine: Mine;
  price: number | null;
  held: boolean;
  /** Name the entry checklist here; a phone keeps it for the card's fold. */
  entry?: boolean;
}) {
  const t = useT();
  const fit = useFit(ticker);
  const drawn = marks(mine.rules, mine.entries, price, held);
  const entry = withEntry ? fit : null;
  if (!drawn.length && !entry) return null;

  return (
    <div className="tk-yours" role="group" aria-label={t("ticker.mine")}>
      {drawn.map((one) => (
        <button
          key={one.kind}
          type="button"
          className={one.tone ? `tk-yours-item tk-is-${one.tone}` : "tk-yours-item"}
          onClick={one.kind === "alert" ? mine.openAlerts : mine.openJournal}
        >
          {t(one.key, one.vars)}
          {one.gap !== null ? (
            <span className="tk-yours-gap">
              {percent(one.gap, { digits: 1, signed: "always", tight: true }) ?? DASH}
            </span>
          ) : null}
        </button>
      ))}
      {entry ? <FitLink fit={entry} /> : null}
    </div>
  );
}

/** The entry checklist alone, for the phone card's fold. */
export function EntryFit({ ticker }: { ticker: string }) {
  const t = useT();
  const fit = useFit(ticker);
  if (!fit) return null;
  return (
    <div className="tk-yours" role="group" aria-label={t("ticker.mine")}>
      <FitLink fit={fit} />
    </div>
  );
}

/** How many of the reader's entry criteria the name meets; null with none set. */
function useFit(ticker: string) {
  // The same answer the fundamentals card's checklist line reads, from the memo.
  const fit = useApi(() => getEntryFit(ticker), [ticker]);
  return fit.state === "loaded" && fit.data.set && fit.data.total ? fit.data : null;
}

function FitLink({ fit }: { fit: NonNullable<ReturnType<typeof useFit>> }) {
  const t = useT();
  return (
    <Link
      className={
        fit.failed
          ? "tk-yours-item tk-is-orange"
          : fit.met === fit.total
            ? "tk-yours-item tk-is-up"
            : "tk-yours-item"
      }
      page="profile"
      params={{ tab: "plan" }}
    >
      {t("ticker.entry_met", { met: fit.met, total: fit.total })}
    </Link>
  );
}
