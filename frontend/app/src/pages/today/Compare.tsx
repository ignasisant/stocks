/**
 * Your positions against their sector and the index — computed, never written.
 *
 * Above the table, the indexes themselves over the span picked — the book as
 * it stands today, the S&P 500, the Nasdaq, the world, emerging markets, the
 * Euro Stoxx, the IBEX, and Bitcoin when the book holds coins — each a button:
 * the one pressed is the index every row's last gap is to (the S&P 500 until
 * another is picked). Every move is in the reader's own currency (the server
 * converts), so a dollar's fall is not read as the positions' skill.
 *
 * One row per position (the largest first, as the server ranks them) over
 * the span picked above the table — the last month, six months, a year, or
 * since the book's first day: its own move, the gap to its sector's ETF and
 * the gap to the index, in percentage points, and the Review page's verdict
 * on it. The table opens since the book's first day: a window that starts
 * later forgives whatever came before it. There the book's tile is its own
 * money and each index's that same money bought into it on the same days.
 * The rows with something to say over the span — a gap of five points or
 * more, or a verdict that asks for a move, on a position of 1 % or more —
 * come first and carry a mark.
 *
 * Below the main column's narrow width the table becomes dense rows: the
 * symbol and verdict on top, the gaps under them.
 */

import { useState } from "react";
import { calendarDay } from "../../shell/dates";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Chip, toneOf, type ChipSpec } from "../../ui/Kpi";
import { DenseRows, Responsive } from "../../ui/Rows";
import { decimal, percent } from "../home/format";
import { TickerCell } from "../home/ui";
import { verdictTone } from "../review/format";
import type { Verdict } from "../review/types";
import {
  BOOK,
  INCEPTION,
  SPANS,
  compareData,
  compareOrder,
  notable,
  openingSpan,
  pickBench,
  type CompareData,
  type Span,
} from "./card";
import type { TodayBenchmark, TodayRow, TodaySection } from "./types";
import { Segmented } from "../../ui/Segmented";

type Shown = { row: TodayRow; data: CompareData; hot: boolean };

function useFigures() {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  return {
    na,
    pct: (value: number | null, signed = true) =>
      value === null ? na : (percent(value / 100, lang, { signed, digits: 1 }) ?? na),
    pp: (value: number | null) => {
      const text = value === null ? null : decimal(value, lang, 1, { signed: true });
      return text === null ? na : t("today.pp", { value: text });
    },
    verdict: (value: string | null): ChipSpec | null =>
      value
        ? { text: t(`review.verdict_${value}`), tone: verdictTone(value as Verdict) }
        : null,
  };
}

function Move({ value, text }: { value: number | null; text: string }) {
  const sign = toneOf(value);
  return <span className={sign === "flat" ? undefined : `td-${sign}`}>{text}</span>;
}

/** The span picker: one month, six months, a year, since the first day. */
function SpanPicker({
  value,
  since,
  onChange,
}: {
  value: Span;
  since: boolean;
  onChange: (next: Span) => void;
}) {
  const t = useT();
  // A card stored before the book's first day was carried has no such span.
  const spans = SPANS.filter((span) => since || span !== INCEPTION);
  return (
    <Segmented
      className="td-seg"
      label={t("today.col_span")}
      items={spans.map((span) => ({ id: span, label: t(`today.col_${span}`) }))}
      value={value}
      onPick={onChange}
    />
  );
}

/** The book's and each index's move over `span`; the pressed one is the
 *  index the rows' last gap is to. */
function Benchmarks({
  marks,
  span,
  picked,
  currency,
  since,
  onPick,
}: {
  marks: TodayBenchmark[];
  span: Span;
  picked: string | undefined;
  currency: string;
  since: string;
  onPick: (symbol: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const f = useFigures();
  const all = span === INCEPTION;
  const help = (mark: TodayBenchmark) =>
    mark.symbol === BOOK
      ? t(all ? "today.bench_book_all_help" : "today.bench_book_help")
      : all
        ? t("today.bench_same_money", { symbol: mark.symbol })
        : mark.symbol;
  return (
    <div className="td-bench" role="group" aria-label={t("today.bench_pick")}>
      {marks.map((mark) => {
        const name =
          mark.symbol === BOOK
            ? t(all ? "today.bench_book_all" : "today.bench_book")
            : mark.name;
        const move = mark[span] ?? null;
        return (
          <button
            key={mark.symbol}
            type="button"
            className="td-bench-item"
            aria-pressed={mark.symbol === picked}
            title={help(mark)}
            onClick={() => onPick(mark.symbol)}
          >
            <span className="td-bench-name">{name}</span>
            <Move value={move} text={f.pct(move)} />
          </button>
        );
      })}
      {all && since ? (
        <span className="td-bench-ccy">
          {t("today.bench_since", { ccy: currency, date: calendarDay(since, lang) })}
        </span>
      ) : currency ? (
        <span className="td-bench-ccy">{t("today.bench_ccy", { ccy: currency })}</span>
      ) : null}
    </div>
  );
}

export function Compare({ section }: { section: TodaySection }) {
  const t = useT();
  const lang = useLang();
  const f = useFigures();
  const [span, setSpan] = useState<Span>(() => openingSpan(section));
  const [picked, setPicked] = useState<string | null>(null);
  const marks = section.benchmarks ?? [];
  const bench = pickBench(marks, picked);
  const benchName = !bench
    ? null
    : bench.symbol === BOOK
      ? t("today.bench_book")
      : bench.name;
  const vsIndex = benchName
    ? t("today.col_vs", { name: benchName })
    : t("today.col_vs_index");
  const shown: Shown[] = compareOrder(section.rows, span).map((row) => {
    const data = compareData(row, span, bench);
    return { row, data, hot: notable(data) };
  });
  // Since inception, a name listed after the book began is measured from
  // its listing, and every gap on its row over that same window.
  const listedLater = (row: TodayRow) =>
    span === INCEPTION && typeof row.data.all_from === "string"
      ? t("today.all_from", { date: calendarDay(row.data.all_from, lang) })
      : undefined;
  // A benchmark that does not apply to a row (Bitcoin against itself, a
  // coin without a sector) is a dash, not "n/a": nothing is missing.
  const gap = (value: number | null, applies: boolean) => (applies ? f.pp(value) : "—");

  // A column no row fills is left out: a book of funds has no sector to
  // beat, and Review does not value a coin.
  const sectors = shown.some(({ data }) => data.sector_etf);
  const verdicts = shown.some(({ data }) => data.verdict);

  const wide = (
    <div className="td-scroll">
      <table className="hm-table td-compare">
        <thead>
          <tr>
            <th scope="col">{t("today.col_name")}</th>
            <th scope="col" className="hm-num">
              {t("today.col_weight")}
            </th>
            <th scope="col" className="hm-num">
              {t(`today.col_${span}`)}
            </th>
            {sectors ? (
              <th scope="col" className="hm-num">
                {t("today.col_vs_sector")}
              </th>
            ) : null}
            <th scope="col" className="hm-num">
              {vsIndex}
            </th>
            {verdicts ? <th scope="col">{t("today.col_verdict")}</th> : null}
          </tr>
        </thead>
        <tbody>
          {shown.map(({ row, data, hot }) => (
            <tr key={row.key} className={hot ? "td-hot" : undefined}>
              <td>
                <TickerCell ticker={row.tickers[0] ?? ""} />
              </td>
              <td className="hm-num">{f.pct(data.weight, false)}</td>
              <td className="hm-num" title={listedLater(row)}>
                <Move value={data.move} text={f.pct(data.move)} />
              </td>
              {sectors ? (
                <td className="hm-num">
                  {/* The benchmark named before its gap, on the same line: a
                      sector ETF, or Bitcoin for a coin. */}
                  {data.sector_etf ? (
                    <span className="td-etf">{data.sector_etf}</span>
                  ) : null}
                  <Move
                    value={data.vs_sector}
                    text={gap(data.vs_sector, !!data.sector_etf)}
                  />
                </td>
              ) : null}
              <td className="hm-num">
                <Move
                  value={data.vs_index}
                  text={gap(data.vs_index, data.vs_index_applies)}
                />
              </td>
              {verdicts ? (
                <td>
                  <Chip chip={f.verdict(data.verdict)} />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const narrow = (
    <DenseRows
      rows={shown}
      rowKey={(entry) => entry.row.key}
      spec={{
        ticker: (entry) => entry.row.tickers[0] ?? "",
        badge: (entry) => <Chip chip={f.verdict(entry.data.verdict)} />,
        sub: (entry) => [
          entry.data.weight === null ? null : f.pct(entry.data.weight, false),
          entry.data.sector_etf
            ? `vs ${entry.data.sector_etf} ${f.pp(entry.data.vs_sector)}`
            : null,
          entry.data.vs_index === null
            ? null
            : `${vsIndex} ${f.pp(entry.data.vs_index)}`,
        ],
        value: (entry) => (
          <Move value={entry.data.move} text={f.pct(entry.data.move)} />
        ),
        delta: () => t(`today.col_${span}`),
        wrap: true,
      }}
    />
  );

  return (
    <>
      <SpanPicker value={span} since={!!section.since} onChange={setSpan} />
      {marks.length ? (
        <Benchmarks
          marks={marks}
          span={span}
          picked={bench?.symbol}
          currency={section.currency ?? ""}
          since={section.since ?? ""}
          onPick={setPicked}
        />
      ) : null}
      <Responsive wide={wide} narrow={narrow} />
      <Link page="review" className="td-more">
        {t("today.open_review")}
      </Link>
    </>
  );
}
