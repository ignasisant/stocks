/**
 * The decisions the day's card makes without drawing anything — shared by the
 * Today page and Home's teaser, which read the same card.
 *
 * Kept free of React so they are tested as plain functions: when to ask the
 * server to write today's card, what the stamp under the badge says, which
 * lines a teaser keeps, which tabs the page offers and how the market read
 * splits into macro and trends.
 */

import type { DailyCard, DailyItem } from "../home/types";
import { dayKey, monthDay, type Translate } from "../home/format";
import type {
  MarketCard,
  MarketLine,
  MarketSector,
  PersonalCard,
  TodayCard,
  TodayRow,
  TodaySection,
} from "./types";

/**
 * "Today · 09:14" / "2 Sep" — the stamp under the badge.
 *
 * Before the 09:00 cutoff the page shows *yesterday's* card (see
 * `daily.action_day`), so the date is never decoration: it is how the reader
 * knows the briefing predates this morning. The clock is the browser's own,
 * which is the reader's zone.
 */
export function stampOf(
  card: Pick<DailyCard, "day" | "action_day" | "generated">,
  t: Translate,
  now: Date = new Date(),
): string {
  const stamp = card.day ?? card.action_day;
  if (stamp !== dayKey(now)) return monthDay(stamp, t) ?? stamp;
  if (!card.generated) return t("home.daily_today_no_time");
  const at = new Date(card.generated * 1000);
  const clock = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  return t("home.daily_today", { time: clock });
}

/**
 * Whether this card should be written now: it does not stand, nothing is
 * already writing it, and this page has not asked for this day yet.
 */
export function wantsWriting(card: DailyCard, asked: string | null): boolean {
  return (!card.fresh || card.upgradable) && !card.pending && asked !== card.action_day;
}

/** The card's lines as items — its own, or a pre-key card's bullets. */
export function linesOf(card: Pick<DailyCard, "items" | "bullets">): DailyItem[] {
  if (card.items?.length) return card.items;
  return card.bullets.map((line, i) => ({
    key: `line:${i}`,
    kind: "",
    line,
    tickers: [],
  }));
}

/** Whether a line has an analysis to open: a trigger behind it. */
export function opens(item: DailyItem): boolean {
  return item.kind !== "";
}

/** The lines split into the card's two trigger sections, alerts first. */
export function sectionsOf(lines: DailyItem[]): {
  alerts: DailyItem[];
  watch: DailyItem[];
} {
  return {
    alerts: lines.filter((item) => item.section === "alerts"),
    watch: lines.filter((item) => item.section !== "alerts"),
  };
}

/**
 * The note a card earns under it, or null for the model's own disclaimer: the
 * stand-in while the brief or the briefing is written, the default card on a
 * day the brief went unanswered, the computed card said for what it is.
 */
export function noteKey(
  card: Pick<DailyCard, "pending" | "source" | "brief">,
): string | null {
  if (card.pending)
    return card.brief === "pending"
      ? "home.daily_brief_wait"
      : "home.daily_computed_wait";
  if (card.brief === "missed") return "home.daily_brief_missed";
  if (card.source === "computed") return "home.daily_computed_note";
  return null;
}

/**
 * The badge over the card: the default card, once it is final, does not wear
 * the AI label — a reader takes the badge before any note under it.
 */
export function badgeKey(card: Pick<DailyCard, "pending" | "source">): string {
  return card.source === "computed" && !card.pending
    ? "home.daily_badge_computed"
    : "home.daily_badge";
}

/**
 * The colour a table cell earns: a signed figure is a move, and reads green or
 * red; an unsigned one (a weight, a volatility, a multiple) is a level, and
 * stays ink.
 */
export function tone(cell: string): "up" | "down" | null {
  if (cell.startsWith("+")) return "up";
  if (cell.startsWith("-") || cell.startsWith("−")) return "down";
  return null;
}

/** How many lines Home's teaser keeps before it points at the page. */
const TEASER_LINES = 3;

/**
 * The teaser's lines — the fired alerts first, then the card's order — and how
 * much more the page holds: the lines left out plus the Today sections' rows,
 * which the teaser never draws.
 */
export function teaserOf(
  card: Pick<PersonalCard, "items" | "bullets" | "sections" | "today">,
  max: number = TEASER_LINES,
): { lines: DailyItem[]; more: number } {
  const { alerts, watch } = sectionsOf(linesOf(card));
  const brief = (card.sections ?? []).flatMap((section) => section.lines);
  // The brief is the card when there is one: "worth a look" is not on it.
  const ordered = [...alerts, ...(brief.length ? brief : watch)];
  const rows = (card.today ?? []).reduce((n, section) => n + section.rows.length, 0);
  return {
    lines: ordered.slice(0, max),
    more: Math.max(0, ordered.length - max) + rows,
  };
}

/* ----------------------------------------------------------------- the page */

export type TabId =
  | "all"
  | "alerts"
  | "routines"
  | "book"
  | "news"
  | "insiders"
  | "compare"
  | "macro"
  | "trends";

export const TAB_LABELS: Record<TabId, string> = {
  all: "today.tab_all",
  alerts: "today.tab_alerts",
  routines: "today.tab_routines",
  book: "today.tab_book",
  news: "today.tab_news",
  insiders: "today.tab_insiders",
  compare: "today.tab_compare",
  macro: "today.tab_macro",
  trends: "today.tab_trends",
};

/** Market topics read as macro; the rest (trend, sector, crypto) as trends. */
const MACRO_TOPICS = new Set<MarketLine["topic"]>(["rates", "macro"]);

/**
 * The market read's written lines split into the page's two market sections.
 *
 * Only the model's: a computed read's lines are its tiles said again in words
 * ("10-year at 5.22%, +39 bp in a month" under a 10-year tile reading 5.22%,
 * +39 bp), so they are not drawn twice.
 */
export function marketSplit(market: Pick<MarketCard, "lines" | "source"> | null): {
  macro: MarketLine[];
  trends: MarketLine[];
} {
  const lines = market?.source === "llm" ? market.lines : [];
  return {
    macro: lines.filter((line) => MACRO_TOPICS.has(line.topic)),
    trends: lines.filter((line) => !MACRO_TOPICS.has(line.topic)),
  };
}

/** Whether a market section has anything to draw: a line, or a figure. */
function hasMacro(market: MarketCard | null): boolean {
  if (!market) return false;
  return (
    marketSplit(market).macro.length > 0 ||
    market.rates.length > 0 ||
    market.banks.length > 0 ||
    market.inflation.length > 0
  );
}

function hasTrends(market: MarketCard | null): boolean {
  if (!market) return false;
  return (
    marketSplit(market).trends.length > 0 ||
    market.regime !== null ||
    market.sectors.length > 0
  );
}

/** A computed section of the personal card, by id. */
export function sectionOf(
  card: Pick<PersonalCard, "today"> | null,
  id: TodaySection["id"],
): TodaySection | null {
  return card?.today?.find((section) => section.id === id) ?? null;
}

export type Tab = { id: TabId; count: number | null };

/**
 * The tabs the page offers, in reading order: what to act on, then what is
 * yours, then the market. A tab with nothing under it is not offered — a tab
 * that opens on an empty panel is a dead end. "All" always is; its count is
 * none. A count is shown where it is a count of things to read (alerts, news,
 * insiders), not where it is a table or a read.
 */
export function tabsOf(view: Pick<TodayCard, "market" | "personal">): Tab[] {
  const card = view.personal;
  const lines = card ? linesOf(card) : [];
  const { alerts, watch } = sectionsOf(lines);
  const brief = card?.sections ?? [];
  const news = sectionOf(card, "news")?.rows.length ?? 0;
  const insiders = sectionOf(card, "insiders")?.rows.length ?? 0;
  const compare = sectionOf(card, "compare")?.rows.length ?? 0;
  const book = Boolean(card?.book?.rows.length) || (!brief.length && watch.length > 0);
  const tabs: Tab[] = [{ id: "all", count: null }];
  if (alerts.length) tabs.push({ id: "alerts", count: alerts.length });
  if (brief.length) tabs.push({ id: "routines", count: null });
  if (book) tabs.push({ id: "book", count: null });
  if (compare) tabs.push({ id: "compare", count: null });
  if (news) tabs.push({ id: "news", count: news });
  if (insiders) tabs.push({ id: "insiders", count: insiders });
  if (hasMacro(view.market)) tabs.push({ id: "macro", count: null });
  if (hasTrends(view.market)) tabs.push({ id: "trends", count: null });
  return tabs;
}

/** The open tab: the one `?tab=` names when the page offers it, else All. */
export function activeTab(tabs: Tab[], wanted: string | null): TabId {
  return tabs.find((tab) => tab.id === wanted)?.id ?? "all";
}

/** Whether a section is drawn under the open tab. */
export function shows(active: TabId, id: Exclude<TabId, "all">): boolean {
  return active === "all" || active === id;
}

/**
 * The best and the worst sectors over the month against the S&P 500, `n`
 * each, a sector with no figure left out. The two lists never share a sector,
 * however few came back.
 */
export function leadersLaggards(
  sectors: MarketSector[],
  n = 3,
): { leaders: MarketSector[]; laggards: MarketSector[] } {
  // A sector behind the index is not leading it, however the rest did: each
  // list keeps only its own side of zero.
  const ranked = sectors
    .filter((sector) => sector.month !== null && Number.isFinite(sector.month))
    .sort((a, b) => (b.month ?? 0) - (a.month ?? 0));
  return {
    leaders: ranked.filter((sector) => (sector.month ?? 0) > 0).slice(0, n),
    laggards: ranked
      .filter((sector) => (sector.month ?? 0) < 0)
      .reverse()
      .slice(0, n),
  };
}

/** Verdicts that ask for a move — the comparisons worth reading first. */
const ACTING = new Set(["sell", "trim", "add"]);

/** The gap to the sector the server calls notable, in percentage points. */
const NOTABLE_PP = 5;

/** The spans a comparison is measured over (`today_sections.SPANS`). */
export const SPANS = ["m1", "m6", "y1"] as const;
export type Span = (typeof SPANS)[number];
/** The span the server's line and the model's note read. */
export const LINE_SPAN: Span = "m6";

/** A comparison's figures over one span, read off its row. */
export type CompareData = {
  weight: number | null;
  move: number | null;
  sector: string | null;
  sector_etf: string | null;
  vs_sector: number | null;
  vs_index: number | null;
  verdict: string | null;
};

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const str = (value: unknown): string | null =>
  typeof value === "string" && value ? value : null;

export function compareData(row: TodayRow, span: Span = LINE_SPAN): CompareData {
  const d = row.data;
  return {
    weight: num(d.weight),
    move: num(d[span]),
    sector: str(d.sector),
    sector_etf: str(d.sector_etf),
    vs_sector: num(d[`vs_sector_${span}`]),
    vs_index: num(d[`vs_index_${span}`]),
    verdict: str(d.verdict),
  };
}

/** The same test as `today_sections.notable`: a wide gap or a proposed move. */
export function notable(data: CompareData): boolean {
  return (
    (data.vs_sector !== null && Math.abs(data.vs_sector) >= NOTABLE_PP) ||
    (data.verdict !== null && ACTING.has(data.verdict))
  );
}

/** Comparisons with something to say first, the rest in the server's order. */
export function compareOrder(rows: TodayRow[], span: Span = LINE_SPAN): TodayRow[] {
  const ranked = rows.map((row, at) => ({
    row,
    at,
    hot: notable(compareData(row, span)),
  }));
  ranked.sort((a, b) => Number(b.hot) - Number(a.hot) || a.at - b.at);
  return ranked.map((entry) => entry.row);
}

/** The tag naming where a row was read. */
export function sourceKey(row: Pick<TodayRow, "kind" | "source">): string | null {
  if (row.kind === "results") return "today.src_results";
  switch (row.source) {
    case "yahoo":
      return "today.src_yahoo";
    case "8k":
      return "today.src_8k";
    case "sec":
      return "today.src_sec";
    case "bafin":
      return "today.src_bafin";
    default:
      return null;
  }
}

const MISSING: Record<string, string> = {
  yahoo: "today.src_yahoo",
  edgar: "today.src_edgar",
  sec: "today.src_sec",
  bafin: "today.src_bafin",
  prices: "today.src_prices",
  review: "today.src_review",
};

/** The source names a section could not read, as catalog keys. */
export function missingKeys(missing: string[]): string[] {
  return missing.map((source) => MISSING[source]).filter((key): key is string => !!key);
}

/** How often the page asks again while the personal card is written. */
export const POLL_MS = 1500;
/** And while the market read is a session behind and a newer one is coming. */
const MARKET_POLL_MS = 20_000;
/** A poll that never sees the end stops here: the server's job has a timeout. */
const POLL_CAP = 60;

/** When the page should ask again, or null to stop. */
export function nextPoll(
  view: Pick<TodayCard, "market_stale" | "personal">,
  polls: number,
): number | null {
  if (polls >= POLL_CAP) return null;
  if (view.personal?.pending) return POLL_MS;
  if (view.market_stale) return MARKET_POLL_MS;
  return null;
}

/**
 * A row's link, when it is one the page may open: http(s) only. The URL came
 * off a news feed or a filing index, and a `javascript:` there is not a link.
 */
export function safeUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}
