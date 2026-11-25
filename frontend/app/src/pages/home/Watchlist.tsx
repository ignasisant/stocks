/**
 * The watchlist card: what needs a look first («Ahora»), then one group at a
 * time — favourites, a tag, the rest or everything — as chips, with how the
 * group moved today and rows that say more than a price.
 *
 * Names and prices are two reads, as the API intends — `/watchlist` is the
 * stored list and costs nothing, `/home/closes` is the download that can be
 * throttled. Keeping them apart is what lets the rows stand with "n/a" in the
 * price cells when Yahoo says no, instead of the card vanishing with them.
 * Results dates come from `/earnings`, the calendar card's own read (memoised
 * by `shell/api`, so the second ask is free).
 *
 * The figures are daily closes, not a live quote: the column says *last
 * close*, and the day % is close-to-close — re-read from the quote burst only
 * for a name whose own exchange is shut, where the newest bar can be a flat
 * premarket 0%. A name whose market is not quoting right now has its day
 * figure greyed: real, not moving.
 */

import { useState, type ReactNode } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Pending, Skeleton } from "../../shell/Layout";
import { useT, useLang, type Translate } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Chip, chipFor } from "../../ui/Kpi";
import { Segmented } from "../../ui/Segmented";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";
import { Card, Note } from "./ui";
import { monthDay, priceDigits } from "./format";
import type { BuyZone } from "../../api.gen";
import type { EarningsCalendar } from "../earnings/data";
import type { Closes, WatchlistEntry } from "./types";
import { decimal, percent } from "../../shell/format";
import { TickerCell } from "../../shell/tickers";
import {
  NOW_MAX,
  columns,
  earningsByTicker,
  groups,
  inGroup,
  isOdd,
  nowItems,
  openGroup,
  sortRows,
  tally,
  type Group,
  type GroupId,
  type NowItem,
  type SortId,
  type WatchRow,
} from "./watch";

export function WatchlistGroups({
  nonce,
  onRefresh,
  holdsPositions = false,
}: {
  nonce: number;
  onRefresh: () => void;
  /**
   * The book has positions. The refresh button is the escape hatch for stale
   * prices anywhere on the page — the glance and movers included — so it
   * stays for a book whose watchlist is empty.
   */
  holdsPositions?: boolean;
}) {
  const query = useApi(() => get("/watchlist"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton shape="table" rows={5} />}>
      {(data) =>
        data.entries.length === 0 ? (
          <>
            <EmptyWatchlist />
            {holdsPositions ? <RefreshButton onRefresh={onRefresh} /> : null}
          </>
        ) : (
          <Watch entries={data.entries} nonce={nonce} onRefresh={onRefresh} />
        )
      }
    </Loaded>
  );
}

/**
 * "Refresh prices". The page's handler drops the server's price caches before
 * it asks again (`POST /home/refresh`) — without that, asking again answers
 * from the very TTL caches the reader pressed the button to get past.
 */
function RefreshButton({ onRefresh }: { onRefresh: () => void }) {
  const t = useT();
  return (
    <button type="button" className="ag-btn hm-refresh" onClick={onRefresh}>
      {t("home.refresh_prices")}
    </button>
  );
}

function EmptyWatchlist() {
  const t = useT();
  return (
    <Card>
      <h3 className="hm-card-title">{t("home.empty_watchlist_title")}</h3>
      <Note>{t("home.empty_watchlist_body")}</Note>
      <Link page="profile" className="hm-link">
        {t("common.cta_add_tickers")}
      </Link>
    </Card>
  );
}

const SORTS: SortId[] = ["day", "month", "zone", "own"];

function Watch({
  entries,
  nonce,
  onRefresh,
}: {
  entries: WatchlistEntry[];
  nonce: number;
  onRefresh: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [picked, setPicked] = useState<GroupId | null>(null);
  const [sort, setSort] = useState<SortId>("day");
  // Keyed on the list itself: an edit elsewhere re-reads, a re-render does not.
  const key = entries.map((entry) => entry.ticker).join(",");
  const closes = useApi(async () => {
    const answer = await get<Closes>("/home/closes");
    return new Map(answer.rows.map((row) => [row.ticker.toUpperCase(), row]));
    // `key` stands for `entries`, whose array is rebuilt on every render and
    // would re-fetch forever; its joined form does not.
  }, [key, nonce]);
  // Results dates are a garnish: a calendar that fails leaves the column out.
  const calendar = useApi(
    () => get<EarningsCalendar>("/earnings").catch(() => null),
    [key],
  );
  const prices = closes.state === "loaded" ? closes.data : null;
  const dates =
    calendar.state === "loaded" && calendar.data
      ? earningsByTicker(calendar.data.upcoming)
      : null;
  // The names are known before their prices are: rows draw at once, and
  // only the figure cells wait — "n/a" is kept for a price that could not be
  // had, not for one still on its way.
  const loading = closes.state === "loading";

  const all: WatchRow[] = entries.map((entry) => ({
    entry,
    close: prices?.get(entry.ticker.toUpperCase()) ?? null,
    earnings: dates?.get(entry.ticker.toUpperCase()) ?? null,
  }));
  const list = groups(all);
  const open = openGroup(list, picked);
  const shown = sortRows(inGroup(all, open), sort);
  const name = groupName(
    list.find((group) => group.id === open),
    t,
  );

  return (
    <section className="hm-card hm-wl" aria-labelledby="hm-wl-h">
      <header className="hm-wl-head">
        <h2 id="hm-wl-h" className="hm-card-title">
          {t("home.wl_title")} <span className="hm-wl-count">{entries.length}</span>
        </h2>
        <Link page="profile" className="hm-link">
          {t("home.wl_edit")}
        </Link>
      </header>
      <Now items={nowItems(all)} />
      {list.length > 1 ? (
        <ToggleRow label={t("home.wl_groups_label")} className="hm-wl-chips">
          {list.map((group) => (
            <ToggleChip
              key={group.id}
              on={group.id === open}
              onClick={() => setPicked(group.id)}
            >
              {groupName(group, t)} <small>{group.count}</small>
            </ToggleChip>
          ))}
        </ToggleRow>
      ) : null}
      <div className="hm-wl-sum">
        {prices ? <Summary rows={shown} name={name} /> : <span />}
        <div className="hm-wl-sort">
          <span className="hm-wl-sort-l" aria-hidden="true">
            {t("home.wl_sort_label")}
          </span>
          <Segmented
            label={t("home.wl_sort_label")}
            value={sort}
            onPick={setSort}
            items={SORTS.map((id) => ({ id, label: t(`home.wl_sort_${id}`) }))}
          />
        </div>
      </div>
      <Table rows={shown} name={name} loading={loading} lang={lang} sort={sort} />
      <footer className="hm-wl-foot">
        <p className="hm-caption">{t("home.wl_caption")}</p>
        <RefreshButton onRefresh={onRefresh} />
      </footer>
    </section>
  );
}

function groupName(group: Group | undefined, t: Translate): string {
  if (!group) return "";
  if (group.tag !== null) return group.tag;
  return t(group.id === "fav" ? "home.favorites" : `home.wl_group_${group.id}`);
}

function Summary({ rows, name }: { rows: WatchRow[]; name: string }) {
  const t = useT();
  const lang = useLang();
  const { up, down, median } = tally(rows);
  if (median === null) return <span />;
  return (
    <p className="hm-wl-tally">
      <span>
        {t("home.wl_tally", {
          group: name,
          up,
          down,
          median: percent(median, { lang, digits: 1, signed: "always" }),
        })}
      </span>
      <span className="hm-wl-bar" aria-hidden="true">
        <i style={{ flexGrow: up || 0.01 }} />
        <i style={{ flexGrow: down || 0.01 }} />
      </span>
    </p>
  );
}

/** What needs a look first, across the whole list: four lines, then the rest on ask. */
function Now({ items }: { items: NowItem[] }) {
  const t = useT();
  const [more, setMore] = useState(false);
  if (items.length === 0) return null;
  const shown = more ? items : items.slice(0, NOW_MAX);
  return (
    <div className="hm-wl-now">
      <h3 className="hm-wl-eyebrow">{t("home.wl_now")}</h3>
      <ul>
        {shown.map((item) => (
          <li
            key={`${item.kind}:${item.row.entry.ticker}`}
            className={`k-${item.kind}`}
          >
            <span className="hm-wl-kind">{t(`home.wl_kind_${item.kind}`)}</span>
            <TickerCell className="hm-ticker" ticker={item.row.entry.ticker} />
            <span className="hm-wl-why">
              <NowText item={item} />
            </span>
          </li>
        ))}
      </ul>
      {items.length > NOW_MAX ? (
        <button
          type="button"
          className="ag-btn ag-btn-ghost hm-wl-more"
          aria-expanded={more}
          onClick={() => setMore(!more)}
        >
          {more ? t("home.wl_less") : t("home.wl_more", { n: items.length - NOW_MAX })}
        </button>
      ) : null}
    </div>
  );
}

function NowText({ item }: { item: NowItem }) {
  const t = useT();
  const lang = useLang();
  const { close, earnings } = item.row;
  const zone = close?.zone ?? null;
  if (item.kind === "odd")
    return t("home.wl_now_odd", {
      move: percent(close?.pct, { lang, digits: 1, signed: "always" }) ?? "",
      size: decimal(close?.move_size, { lang, digits: 0 }) ?? "",
    });
  if (item.kind === "earn" && earnings)
    return t("home.wl_now_earn", { when: soonDay(earnings.date, earnings.days, t) });
  if (!zone) return null;
  const rule = ruleText(zone, close?.close ?? null, lang, t);
  if (item.kind === "met") return t("home.wl_now_met", { rule });
  if (item.kind === "part")
    return t("home.wl_now_part", { met: zone.met, rules: zone.rules, rule });
  return t("home.wl_now_near", { rule, gap: gapText(zone, lang, t) });
}

/** The rule in words, "cierre en 11,50 o menos" — the daily card's own sentence. */
function ruleText(
  zone: BuyZone,
  price: number | null,
  lang: string,
  t: Translate,
): string {
  const key = `home.daily_crit_${zone.rule ?? ""}`;
  if (!zone.rule || !t.has(key)) return "";
  const digits = zone.rule === "buy_below" ? priceDigits(price ?? zone.level) : 0;
  return t(key, { level: decimal(zone.level, { lang, digits }) ?? "" });
}

/** How far the price rule still is: a % of price, or points of drawdown. */
function gapText(zone: BuyZone, lang: string, t: Translate): string {
  if (zone.gap === null) return "";
  if (zone.rule === "buy_drawdown_high")
    return t("home.wl_gap_pts", { n: decimal(zone.gap, { lang, digits: 0 }) });
  return percent(zone.gap / 100, { lang, digits: 0 });
}

function soonDay(iso: string, days: number, t: Translate): string {
  if (days === 0) return t("home.wl_today");
  if (days === 1) return t("home.wl_tomorrow");
  return monthDay(iso, t) ?? iso;
}

function Table({
  rows,
  name,
  loading,
  lang,
  sort,
}: {
  rows: WatchRow[];
  name: string;
  loading: boolean;
  lang: string;
  sort: SortId;
}) {
  const t = useT();
  const has = columns(rows);
  // The column the rows are sorted on says so: the picker above reads as a
  // period otherwise, and «Día» picked over a table led by «1 mes» confused.
  const head = (by: SortId | null, text: string, num = false) => {
    const on = by !== null && by === sort;
    const cls = [num ? "hm-num" : "", on ? "is-sorted" : ""].filter(Boolean).join(" ");
    return (
      <span
        role="columnheader"
        className={cls || undefined}
        aria-sort={on ? "descending" : undefined}
      >
        {text}
        {on ? <span aria-hidden="true"> ↓</span> : null}
      </span>
    );
  };
  const na: ReactNode = loading ? (
    <Pending />
  ) : (
    <span className="hm-na">{t("home.na")}</span>
  );
  const cls = ["hm-wl-t", has.zone ? "" : "no-z", has.earnings ? "" : "no-e"]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} role="table" aria-label={name} data-sort={sort}>
      <div className="hm-wl-h" role="row">
        {head(null, t("home.wl_col_name"))}
        {head("month", t("home.wl_col_month"))}
        {head(null, t("home.col_last_close"), true)}
        {head("day", t("home.wl_col_day"), true)}
        {has.zone ? head("zone", t("home.wl_col_zone")) : null}
        {has.earnings ? (
          <span role="columnheader">{t("home.wl_col_earnings")}</span>
        ) : null}
      </div>
      {rows.map((row) => (
        <Row key={row.entry.ticker} row={row} has={has} na={na} lang={lang} />
      ))}
    </div>
  );
}

function Row({
  row,
  has,
  na,
  lang,
}: {
  row: WatchRow;
  has: { zone: boolean; earnings: boolean };
  na: ReactNode;
  lang: string;
}) {
  const t = useT();
  const { entry, close, earnings } = row;
  const odd = isOdd(close);
  const move = percent(close?.pct, { lang, digits: 2, signed: "always" });
  const month = close?.month_pct ?? null;
  const dash = <span className="hm-na">—</span>;
  return (
    <div className={odd ? "hm-wl-r is-odd" : "hm-wl-r"} role="row">
      <span className="c-name" role="cell">
        <TickerCell className="hm-ticker" ticker={entry.ticker} />
        <span className="hm-wl-marks">
          {close?.held ? (
            <span className="hm-wl-m held">{t("home.wl_held")}</span>
          ) : null}
          {close?.extreme ? (
            <span className={`hm-wl-m ${close.extreme}`}>
              {t(`home.wl_${close.extreme}`)}
            </span>
          ) : null}
          {odd ? (
            <span
              className="hm-wl-m odd"
              title={t("home.wl_odd_title", {
                size: decimal(close?.move_size, { lang, digits: 0 }) ?? "",
              })}
            >
              {t("home.wl_odd")}
            </span>
          ) : null}
          {entry.tags.map((tag) => (
            <span key={tag} className="hm-wl-tag">
              {tag}
            </span>
          ))}
        </span>
      </span>
      <span className="c-m" role="cell">
        {month === null ? (
          close ? (
            dash
          ) : (
            na
          )
        ) : (
          <>
            <Spark values={close?.spark ?? []} up={month >= 0} />
            <span className={month >= 0 ? "pos" : "neg"}>
              {percent(month, { lang, digits: 1, signed: "always" })}
            </span>
          </>
        )}
      </span>
      <span className="c-px hm-num" role="cell">
        {decimal(close?.close, { lang, digits: priceDigits(close?.close) }) ?? na}
      </span>
      <span className="c-d hm-num" role="cell">
        {move === null ? (
          na
        ) : (
          <Chip chip={chipFor(close?.pct, move, close?.active === false)} />
        )}
      </span>
      {has.zone ? (
        <span className="c-z" role="cell">
          <ZoneCell zone={close?.zone ?? null} price={close?.close ?? null} />
        </span>
      ) : null}
      {has.earnings ? (
        <span className="c-e" role="cell">
          {earnings ? (
            <span className="hm-wl-e" title={earnings.date}>
              {soonDay(earnings.date, earnings.days, t)}
            </span>
          ) : (
            dash
          )}
        </span>
      ) : null}
    </div>
  );
}

function ZoneCell({ zone, price }: { zone: BuyZone | null; price: number | null }) {
  const t = useT();
  const lang = useLang();
  if (!zone) return <span className="hm-na">—</span>;
  const part = zone.state === "met" && zone.met < zone.rules;
  const tone = part ? "part" : zone.state;
  const text =
    zone.state === "met"
      ? t(part ? "home.wl_zone_part" : "home.wl_zone_met")
      : zone.gap === null
        ? "—"
        : t("home.wl_zone_gap", { gap: gapText(zone, lang, t) });
  return (
    <span className={`hm-wl-z z-${tone}`} title={ruleText(zone, price, lang, t)}>
      {text}
    </span>
  );
}

/** The month as a line: shape, not level. Colour from the class, as the page's other sparks. */
function Spark({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const points = values
    .map((value, i) => {
      const x = (i / (values.length - 1)) * 42 + 1;
      const y = 2 + (1 - (value - lo) / span) * 14;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className={up ? "hm-wl-spark up" : "hm-wl-spark down"}
      viewBox="0 0 44 18"
      aria-hidden="true"
    >
      <polyline points={points} />
    </svg>
  );
}
