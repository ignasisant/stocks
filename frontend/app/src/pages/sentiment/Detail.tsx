/**
 * Three minutes: the seven long tables behind one tab strip.
 *
 * Almost every line here is the same shape — the level, the change over four
 * horizons, a sparkline, and where the series sits in its own trend — so a
 * reader learns one layout instead of seven. That is also why the tables share
 * a renderer: seven hand-written tables are seven chances for the columns to
 * drift apart, and the whole point of the shape is that it repeats.
 *
 * Two rules the blocks exist to keep. A change is coloured by the row's own
 * `welcome` crossed with the sign, never by the sign alone. And a block whose
 * source died keeps its place and says which source: an absent block reads as
 * "nothing is happening here", which is a different and wrong claim.
 */

import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { Spark } from "./Spark";
import {
  NA,
  adaptive,
  changeText,
  fixed,
  grouped,
  maybe,
  percent,
  sectorKey,
  share,
  slug,
  tone,
  toneClass,
} from "./format";
import type { TrendBlock, TrendRow, TrendTables } from "./types";

/** Who to name when a block cannot be drawn. Not translated: they are names. */
const YAHOO = "Yahoo Finance";
const FRED = "FRED";
const EUROSTAT = "Eurostat";

/**
 * The trend label's slow average, in sessions. Mirrors
 * `stocks.analysis.sentiment.TREND_SLOW`, which the API does not send: it is
 * part of the sentence explaining what the trend column compares against.
 */
const TREND_SLOW = 100;

const HORIZONS = ["week", "month", "quarter", "year"] as const;

type Spec = {
  key: string;
  title: string;
  labelCol: string;
  valueCol: string;
  /** `{n}` is filled with the rows actually shown, so the count is never a lie. */
  source: string;
  countsRows: boolean;
  note: string;
  origin: string;
  /** Which "source is down" copy fits: a price feed or a macro publisher. */
  family: "prices" | "macro";
  /**
   * The source line for a block that has no rows. `source` cannot serve: it
   * counts rows, and a block that is down has none — "0 gauges · Yahoo
   * Finance" is a claim about the market rather than about the fetch. Only the
   * price blocks have a count-free key; FRED and Eurostat keep their own name.
   */
  downSource?: string;
};

const SPECS: Spec[] = [
  {
    key: "indices",
    title: "sentiment.indices_title",
    labelCol: "sentiment.col_index",
    valueCol: "sentiment.col_last",
    source: "sentiment.src_prices",
    countsRows: true,
    note: "sentiment.trend_help",
    origin: YAHOO,
    family: "prices",
    downSource: "sentiment.src_yahoo",
  },
  {
    key: "gauges",
    title: "sentiment.risk_title",
    labelCol: "sentiment.col_gauge",
    valueCol: "sentiment.col_level",
    source: "sentiment.src_gauges",
    countsRows: true,
    note: "sentiment.risk_help",
    origin: YAHOO,
    family: "prices",
    downSource: "sentiment.src_yahoo",
  },
  {
    key: "rates",
    title: "sentiment.rates_title",
    labelCol: "sentiment.col_rate",
    valueCol: "sentiment.col_level",
    source: "sentiment.src_fred",
    countsRows: true,
    note: "sentiment.rates_help",
    origin: FRED,
    family: "macro",
  },
  {
    key: "inflation",
    title: "sentiment.inflation_title",
    labelCol: "sentiment.col_area",
    valueCol: "sentiment.col_headline",
    source: "sentiment.src_inflation",
    countsRows: true,
    note: "sentiment.inflation_help",
    origin: EUROSTAT,
    family: "macro",
  },
  {
    key: "rotation",
    title: "sentiment.rotation_title",
    labelCol: "sentiment.col_sector",
    valueCol: "sentiment.col_excess_month",
    source: "sentiment.src_rotation",
    countsRows: false,
    note: "sentiment.rotation_help",
    origin: YAHOO,
    family: "prices",
    downSource: "sentiment.src_yahoo",
  },
  {
    key: "factors",
    title: "sentiment.factors_title",
    labelCol: "sentiment.col_pair",
    valueCol: "sentiment.col_ratio",
    source: "sentiment.src_factors",
    countsRows: true,
    note: "sentiment.factors_help",
    origin: YAHOO,
    family: "prices",
    downSource: "sentiment.src_yahoo",
  },
  {
    key: "cross",
    title: "sentiment.cross_title",
    labelCol: "sentiment.col_asset",
    valueCol: "sentiment.col_last",
    source: "sentiment.src_prices",
    countsRows: true,
    note: "sentiment.cross_help",
    origin: YAHOO,
    family: "prices",
    downSource: "sentiment.src_yahoo",
  },
];

type T = (key: string, slots?: Record<string, string | number>) => string;

/** The level, in the units this block quotes its own rows in. */
function level(block: string, value: number | null): string {
  if (value === null) return NA;
  if (block === "indices") return grouped(value);
  if (block === "gauges") return fixed(value, 1);
  if (block === "rates") return fixed(value, 2, "%");
  if (block === "inflation") return fixed(value, 1, "%");
  // A pair's ratio is a small number whose third decimal is the news: 1.043
  // against 1.041 is the week's whole move.
  if (block === "factors") return fixed(value, 3);
  return adaptive(value);
}

/**
 * The value column, which is not always a level.
 *
 * Rotation answers "which sectors led", and the answer is a difference of two
 * numbers rather than either of them: the sector ETF's own price says nothing
 * a reader can act on, so the column carries its excess return over the S&P
 * for the month — the same figure the Streamlit table quotes, under the same
 * heading.
 */
function valueText(block: TrendBlock, row: TrendRow): string {
  if (block.block !== "rotation") return level(block.block, row.value);
  const excess = row.changes.month;
  return excess === undefined ? NA : changeText(block.unit, excess);
}

/**
 * What a row is called, what it means, and the sentence explaining it.
 *
 * The key each block is indexed by differs — a ticker, a FRED id, an area code
 * — and so does the catalog key built from it. A row the catalogs have nothing
 * to say about simply gets no dot, rather than a dotted key printed as text.
 */
function describe(t: T, block: string, row: TrendRow) {
  if (block === "rates") {
    // `name` here is the i18n suffix the API carries through from RATE_ROWS.
    return {
      label: maybe(t, `sentiment.${row.name}`) ?? row.name,
      sub: maybe(t, `sentiment.${row.name}_help`),
      tip: maybe(t, `sentiment.tip_rate_${row.name}`),
    };
  }
  if (block === "inflation") {
    return {
      label: maybe(t, `sentiment.area_${row.key}`) ?? row.key,
      sub: undefined,
      tip: maybe(t, `sentiment.tip_area_${row.key}`),
    };
  }
  if (block === "factors") {
    // `key` is the pair id (`growth_value`), and `name` is the two tickers it
    // divides — which is what the tooltip explains and the label must not be.
    return {
      label: maybe(t, `sentiment.pair_${row.key}`) ?? row.name,
      sub: row.name,
      tip: maybe(t, `sentiment.tip_pair_${row.key}`),
    };
  }
  if (block === "rotation") {
    const key = sectorKey(row.name);
    return {
      label: maybe(t, `sentiment.sector_${key}`) ?? row.name,
      sub: undefined,
      tip: maybe(t, `sentiment.tip_sector_${key}`),
    };
  }
  if (block === "gauges") {
    return {
      label: row.name || row.key,
      sub: maybe(t, `sentiment.gauge_${slug(row.key)}_sub`),
      tip: maybe(t, `sentiment.tip_gauge_${slug(row.key)}`),
    };
  }
  if (block === "indices") {
    return {
      label: row.name || row.key,
      sub:
        row.weight === null
          ? undefined
          : t("sentiment.index_weight", { pct: share(row.weight) }),
      tip: maybe(t, `sentiment.tip_index_${slug(row.key)}`),
    };
  }
  return {
    label: row.name || row.key,
    // The dollar reaches a euro reader twice: here as a price, and in the book
    // as part of its market value.
    sub: row.key === "EURUSD=X" ? t("sentiment.fx_base") : undefined,
    tip: maybe(t, `sentiment.tip_asset_${slug(row.key)}`),
  };
}

type Cell = { label: string; text: string; tone: number };

/**
 * The comparison columns a block quotes, in order.
 *
 * Four horizons is the page's default and the reason the rows line up down the
 * whole screen, but two blocks do not have four:
 *
 * * The **gauges** trade their twelve-month column for a percentile pair — a
 *   percent change over a year on a mean-reverting series is close to
 *   meaningless.
 * * The **rotation** block trades three of its horizons for the reader's own
 *   position: which sectors led over a quarter, what share of this book sits
 *   in each, what share of the index does, and the difference. A sector's
 *   excess return over a week is noise; the gap between holding 14% of it and
 *   the index holding 6% is not.
 * * The **inflation** block has no horizons at all. `macro.inflation()` is one
 *   row per area, published twelve times a year, and the API sends the two
 *   comparisons that source already decided mean something — the change since
 *   the previous print and the change since six months ago — plus the month it
 *   refers to. Asking it for a "week" change is arithmetic on data that does
 *   not exist, and the four empty columns it produced were exactly that.
 *
 * `headers` and `cells` must return the same number of entries: the row is a
 * grid, and a header that outnumbers its cells silently shifts every column.
 */
function headers(t: T, block: string): string[] {
  if (block === "gauges") {
    return [
      ...HORIZONS.slice(0, 3).map((name) => t(`sentiment.h_${name}`)),
      t("sentiment.col_pctl"),
    ];
  }
  if (block === "inflation") {
    return [
      t("sentiment.col_core"),
      t("sentiment.col_vs_prior"),
      t("sentiment.col_vs_six"),
      t("sentiment.col_period"),
    ];
  }
  if (block === "rotation") {
    return [
      t("sentiment.col_excess_quarter"),
      t("sentiment.col_your_weight"),
      t("sentiment.col_spy_weight"),
      t("sentiment.col_tilt"),
    ];
  }
  return HORIZONS.map((name) => t(`sentiment.h_${name}`));
}

/**
 * The comparison cells for one row.
 *
 * A comparison absent from `changes` is a series too short to have one, which
 * is not "no change" — so it prints `n/a` and stays uncoloured.
 */
function cells(t: T, block: TrendBlock, row: TrendRow): Cell[] {
  const labels = headers(t, block.block);
  const cell = (label: string, change: number | undefined): Cell =>
    change === undefined
      ? { label, text: NA, tone: 0 }
      : {
          label,
          text: changeText(block.unit, change),
          tone: tone(change, row.welcome),
        };

  if (block.block === "rotation") {
    // Weights are shares of a book and of an index: neither is welcome news
    // nor bad, so neither is coloured. Only the excess return is a verdict.
    const weight = (value: number | null, label: string): Cell => ({
      label,
      text: value === null ? NA : share(value, 1),
      tone: 0,
    });
    const tilt =
      row.weight === null || row.spy_weight === null
        ? null
        : row.weight - row.spy_weight;
    return [
      cell(labels[0] ?? "", row.changes.quarter),
      weight(row.weight, labels[1] ?? ""),
      weight(row.spy_weight, labels[2] ?? ""),
      {
        label: labels[3] ?? "",
        // Percentage POINTS, and signed: a tilt is the distance between two
        // shares, and writing it as a percentage invites reading 8pp of the
        // book as 8% of it.
        text:
          tilt === null ? NA : `${tilt >= 0 ? "+" : ""}${(tilt * 100).toFixed(1)}pp`,
        tone: 0,
      },
    ];
  }

  if (block.block === "inflation") {
    return [
      // The rate with food and energy taken out, uncoloured: it is a second
      // level, not a change, and the headline beside it is the one the
      // direction colours belong to.
      {
        label: labels[0] ?? "",
        text: row.core === null ? NA : fixed(row.core, 1, "%"),
        tone: 0,
      },
      cell(labels[1] ?? "", row.changes.print),
      cell(labels[2] ?? "", row.changes.half_year),
      // The reference month, which rides in `name` because each area prints on
      // its own: the euro-area flash estimate and the US CPI release are weeks
      // apart, and one "latest" over both silently misdates one of them.
      { label: labels[3] ?? "", text: row.name || NA, tone: 0 },
    ];
  }

  const gauges = block.block === "gauges";
  const horizons = gauges ? HORIZONS.slice(0, 3) : HORIZONS;
  const out: Cell[] = horizons.map((name, i) =>
    cell(labels[i] ?? "", row.changes[name]),
  );
  if (gauges) {
    // Uncoloured, always: a percentile is a position, not a verdict.
    const now = row.percentile;
    const then = row.percentile_then;
    const text =
      now === null
        ? NA
        : then === null
          ? `p${now.toFixed(0)}`
          : `p${now.toFixed(0)} (${then.toFixed(0)})`;
    out.push({ label: t("sentiment.col_pctl"), text, tone: 0 });
  }
  return out;
}

function Row({
  t,
  block,
  row,
  sub,
}: {
  t: T;
  block: TrendBlock;
  row: TrendRow;
  sub?: string;
}) {
  const meta = describe(t, block.block, row);
  const note = sub ?? meta.sub;
  return (
    <div className={row.stale ? "sn-trend-row sn-dim" : "sn-trend-row"}>
      <div className="sn-trend-lc">
        <span className="sn-trend-n">
          <span className="sn-trend-l" title={meta.tip ?? meta.label}>
            {meta.label}
          </span>
          {/* The dot only appears where there is something to say. A row whose
              name explains itself would gain nothing from one, and a dot on
              every row teaches the reader to stop looking. */}
          {meta.tip && (
            <span className="sn-trend-i" tabIndex={0} data-tip={meta.tip}>
              i
            </span>
          )}
        </span>
        {note && <span className="sn-trend-sub">{note}</span>}
      </div>
      <span className="sn-trend-v">{valueText(block, row)}</span>
      {cells(t, block, row).map((cell) => (
        <span
          className={`sn-trend-c ${toneClass(cell.tone)}`}
          data-h={cell.label}
          key={cell.label}
        >
          {cell.text}
        </span>
      ))}
      <span className="sn-trend-s">
        <Spark values={row.spark} state={row.state} />
      </span>
      {row.state ? (
        <span className={`sn-trend-st sn-st-${row.state}`}>
          {t(`sentiment.state_${row.state}`)}
        </span>
      ) : (
        <span className="sn-trend-st" />
      )}
    </div>
  );
}

/**
 * A block whose source died: in place, named, and with a way back.
 *
 * The reader learns exactly what is missing rather than only that something
 * is — a Yahoo throttle clears in a minute and a FRED outage does not, and the
 * two are this page's most common failures.
 */
function Down({
  spec,
  reason,
  onRetry,
}: {
  spec: Spec;
  reason: string;
  onRetry: () => void;
}) {
  const t = useT();
  const family =
    spec.family === "prices"
      ? "sentiment.prices_unavailable"
      : "sentiment.macro_unavailable";
  // The reason the API gave, in the reader's own terms; `no_data` has no copy
  // of its own, so it falls back to the block's own family message.
  const body =
    reason === "rate_limited"
      ? "common.rate_limited"
      : reason === "offline"
        ? "common.offline"
        : family;
  return (
    <>
      <div className="sn-sec-head">
        <span className="sn-tcard-w">{t(spec.title)}</span>
        <span className="sn-spacer" />
        <span className="sn-mono">
          {spec.downSource ? t(spec.downSource) : spec.origin}
        </span>
      </div>
      <div className="sn-down">
        <span className="sn-down-t">{t(`${family}_title`)}</span>
        <span className="sn-down-b">{t(body)}</span>
      </div>
      <button className="sn-btn" onClick={onRetry}>
        {t("sentiment.down_retry")}
      </button>
      <p className="sn-caption">
        {t("sentiment.down_stamp", {
          time: new Date().toLocaleTimeString(),
          source: spec.origin,
        })}
      </p>
    </>
  );
}

function Table({
  spec,
  block,
  capture,
}: {
  spec: Spec;
  block: TrendBlock;
  capture: number | null;
}) {
  const t = useT();
  const heads = headers(t, block.block);

  // The Chicago Fed's financial conditions index rides in the rates block
  // because one FRED call fetches it, and it does not belong in that table: it
  // is an index, not a rate, so its level is not a percent and its changes are
  // not basis points. Quoted as a sentence under the table instead, which is
  // where the Streamlit page puts it — and taken out of the rows, or the
  // block's own units would misread every figure on its line.
  const conditions =
    block.block === "rates"
      ? (block.rows.find((row) => row.key === "NFCI") ?? null)
      : null;
  const rows = conditions ? block.rows.filter((row) => row !== conditions) : block.rows;

  // The indices are reordered by the geography the reader holds, and say so —
  // a pinned order claims "these matter to you" without saying how much.
  const pinned = block.block === "indices" && rows.some((row) => row.weight !== null);
  // A sector the reader does not hold is not a blank: not holding it is an
  // active underweight, and the largest ones are the rows a blank would hide.
  const held = block.block === "rotation" && rows.some((r) => r.weight !== null);
  const top = held
    ? rows.reduce((best, row) => ((row.weight ?? 0) > (best.weight ?? 0) ? row : best))
    : null;

  const notes = [
    pinned ? t("sentiment.indices_pinned") : "",
    spec.key === "indices" ? t(spec.note, { n: TREND_SLOW }) : t(spec.note),
    // "vs 6m" is the annual rate now minus the annual rate six months ago, and
    // is not a three-month annualised figure — a distinction worth a sentence,
    // since the column would otherwise be read as the latter.
    spec.key === "inflation" ? t("sentiment.inflation_momentum_help") : "",
    capture !== null && spec.key === "rotation"
      ? t("sentiment.rotation_capture", { value: percent(capture, 2) })
      : "",
    conditions && conditions.value !== null
      ? t("sentiment.nfci_note", {
          value: conditions.value.toFixed(2),
          change:
            conditions.changes.quarter === undefined
              ? NA
              : conditions.changes.quarter.toFixed(2),
        })
      : "",
  ].filter(Boolean);

  return (
    <>
      <div className="sn-sec-head">
        <span className="sn-tcard-w">{t(spec.title)}</span>
        <span className="sn-spacer" />
        <span className="sn-mono">
          {spec.countsRows ? t(spec.source, { n: rows.length }) : t(spec.source)}
        </span>
      </div>
      {/* Most blocks quote four comparisons; the gauges and the inflation
          print quote three and four of their own. The count rides on the
          wrapper so the header and every row share one grid — a block that
          sized its own columns would line up with nothing. */}
      <div className={`sn-trend sn-trend-${heads.length}`}>
        <div className="sn-trend-head">
          <span className="sn-trend-l">{t(spec.labelCol)}</span>
          <span className="sn-trend-v">{t(spec.valueCol)}</span>
          {heads.map((head) => (
            <span className="sn-trend-c" key={head}>
              {head}
            </span>
          ))}
          <span className="sn-trend-c">{t("sentiment.col_shape")}</span>
          <span className="sn-trend-st">{t("sentiment.col_trend")}</span>
        </div>
        {rows.map((row) => (
          <Row
            key={row.key}
            t={t}
            block={block}
            sub={
              !held
                ? undefined
                : row === top
                  ? t("sentiment.sector_top")
                  : (row.weight ?? 0) <= 0
                    ? t("sentiment.sector_not_held")
                    : undefined
            }
            row={row}
          />
        ))}
      </div>
      <p className="sn-caption">{notes.join(" ")}</p>
    </>
  );
}

export function Detail({
  tables,
  capture,
  onRetry,
}: {
  tables: TrendTables;
  capture: number | null;
  onRetry: () => void;
}) {
  const t = useT();
  const { params, setParams } = useRoute();
  const wanted = params.get("tab") ?? "";
  const active = SPECS.some((spec) => spec.key === wanted) ? wanted : "indices";
  const spec = SPECS.find((entry) => entry.key === active) ?? SPECS[0];
  const block = tables.blocks.find((entry) => entry.block === active);
  if (!spec) return null;

  return (
    <>
      <div className="sn-sec-head">
        <h3 className="sn-sec-t" id="ag-detail">
          {t("sentiment.detail_title")}
        </h3>
        <span className="sn-mono">{t("sentiment.detail_hint")}</span>
      </div>
      <div className="sn-tabs" role="tablist">
        {SPECS.map((entry) => {
          const rows = tables.blocks.find((b) => b.block === entry.key)?.rows.length;
          return (
            <button
              key={entry.key}
              role="tab"
              aria-selected={entry.key === active}
              className={entry.key === active ? "sn-tab sn-tab-on" : "sn-tab"}
              // A tab is not a navigation the back button should walk through.
              onClick={() => setParams({ tab: entry.key })}
            >
              {t(entry.title)}
              {rows ? <span className="sn-tab-n">{rows}</span> : null}
            </button>
          );
        })}
      </div>
      {/* A block with no rows is a block whose source died, whether or not the
          API named a reason for it. */}
      <div role="tabpanel" className="sn-tabpanel">
        {block && block.rows.length > 0 ? (
          <Table spec={spec} block={block} capture={capture} />
        ) : (
          <Down
            spec={spec}
            reason={block?.unavailable ?? "no_data"}
            onRetry={onRetry}
          />
        )}
      </div>
    </>
  );
}
