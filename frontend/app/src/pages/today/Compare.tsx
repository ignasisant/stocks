/**
 * Your positions against their sector and the index — computed, never written.
 *
 * One row per position (the largest first, as the server ranks them) over
 * the span picked above the table — the last month, six months or a year: its
 * own move, the gap to its sector's ETF and the gap to the S&P 500, in
 * percentage points, and the Review page's verdict on it. Six months is the
 * default because it is the span the model's remark and the server's line
 * read. The rows with something to say over that span — a gap of five points
 * or more, or a verdict that asks for a move — come first and carry a mark.
 *
 * Below the main column's narrow width the table becomes dense rows: the
 * symbol and verdict on top, the gaps under them.
 */

import { useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Chip, toneOf, type ChipSpec } from "../../ui/Kpi";
import { DenseRows, Responsive } from "../../ui/Rows";
import { decimal, percent } from "../home/format";
import { TickerCell } from "../home/ui";
import { verdictTone } from "../review/format";
import type { Verdict } from "../review/types";
import {
  LINE_SPAN,
  SPANS,
  compareData,
  compareOrder,
  notable,
  type CompareData,
  type Span,
} from "./card";
import type { TodayRow } from "./types";

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

/** The span picker: one month, six months, a year. */
function SpanPicker({
  value,
  onChange,
}: {
  value: Span;
  onChange: (next: Span) => void;
}) {
  const t = useT();
  return (
    <div className="td-seg" role="group" aria-label={t("today.col_span")}>
      {SPANS.map((span) => (
        <button
          key={span}
          type="button"
          className={span === value ? "td-seg-on" : undefined}
          aria-pressed={span === value}
          onClick={() => onChange(span)}
        >
          {t(`today.col_${span}`)}
        </button>
      ))}
    </div>
  );
}

export function Compare({ rows }: { rows: TodayRow[] }) {
  const t = useT();
  const f = useFigures();
  const [span, setSpan] = useState<Span>(LINE_SPAN);
  const shown: Shown[] = compareOrder(rows, span).map((row) => {
    const data = compareData(row, span);
    return { row, data, hot: notable(data) };
  });

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
              {t("today.col_vs_index")}
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
              <td className="hm-num">
                <Move value={data.move} text={f.pct(data.move)} />
              </td>
              {sectors ? (
                <td className="hm-num">
                  {/* The benchmark named before its gap, on the same line: a
                      sector ETF, or Bitcoin for a coin. */}
                  {data.sector_etf ? (
                    <span className="td-etf">{data.sector_etf}</span>
                  ) : null}
                  <Move value={data.vs_sector} text={f.pp(data.vs_sector)} />
                </td>
              ) : null}
              <td className="hm-num">
                <Move value={data.vs_index} text={f.pp(data.vs_index)} />
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
            : `${t("today.col_vs_index")} ${f.pp(entry.data.vs_index)}`,
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
      <SpanPicker value={span} onChange={setSpan} />
      <Responsive wide={wide} narrow={narrow} />
      <Link page="review" className="td-more">
        {t("today.open_review")}
      </Link>
    </>
  );
}
