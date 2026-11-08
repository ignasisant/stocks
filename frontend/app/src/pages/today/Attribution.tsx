/**
 * Who moved the day: the book's day in money, taken apart — computed, never
 * written.
 *
 * The names that added most and took most away, each with its share of the
 * book in percentage points; then every block (a sector of single names, a
 * fund on its own, the coins), which sum to the day to the cent. Under them
 * the moves past two of their own deviations set against their sector's ETF
 * — the sector's day or the company's — and the last sessions against the
 * index. A position whose 0 % is yesterday's bar repeated is named, not
 * counted as a quiet day.
 */

import { useLang, useT } from "../../shell/i18n";
import { toneOf } from "../../ui/Kpi";
import type {
  DailyAttribution,
  DailyAttributionBlock,
  DailyContribution,
} from "../home/types";
import { maybe } from "../sentiment/format";
import { decimal, money, percent } from "../../shell/format";
import { TickerCell } from "../../shell/tickers";

function useFigures(currency: string) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  return {
    money: (value: number) => money(value, { currency, lang, signed: "always" }) ?? na,
    pct: (value: number | null) =>
      value === null
        ? na
        : (percent(value / 100, { lang, signed: "always", digits: 1 }) ?? na),
    pp: (value: number | null) => {
      const text =
        value === null ? null : decimal(value, { lang, digits: 2, signed: "always" });
      return text === null ? null : t("today.pp", { value: text });
    },
  };
}

function tone(value: number | null) {
  const sign = toneOf(value);
  return sign === "flat" ? undefined : `td-${sign}`;
}

/** A block's name: the sector in the reader's language (Yahoo's spelling
 * when the catalog has none), the fund's logo and link, or the coins. */
function BlockName({ block }: { block: DailyAttributionBlock }) {
  const t = useT();
  if (block.kind === "fund")
    return <TickerCell className="hm-ticker" ticker={block.label} name={false} />;
  const key =
    block.kind === "crypto" ? "crypto" : block.label.toLowerCase().replace(/\W+/g, "_");
  return <span>{maybe(t, `sentiment.sector_${key}`) ?? block.label}</span>;
}

function Side({
  title,
  rows,
  figures,
}: {
  title: string;
  rows: DailyContribution[];
  figures: ReturnType<typeof useFigures>;
}) {
  if (!rows.length) return null;
  return (
    <div className="td-attr-side">
      <h3 className="td-attr-head">{title}</h3>
      <ul className="td-attr-rows">
        {rows.map((row) => (
          <li key={row.ticker} className="ag-row-reach">
            <TickerCell className="hm-ticker" ticker={row.ticker} name={false} />
            <span className="td-attr-fig">
              <strong className={tone(row.amount)}>{figures.money(row.amount)}</strong>
              <small>{figures.pp(row.pp)}</small>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DayAttribution({
  data,
  currency,
  index,
}: {
  data: DailyAttribution;
  currency: string;
  /** The index's display name, "S&P 500". */
  index: string;
}) {
  const t = useT();
  const figures = useFigures(currency);
  const alpha = data.alpha;
  return (
    <div className="td-attr">
      {data.up.length || data.down.length ? (
        <div className="td-attr-sides">
          <Side title={t("today.day_up")} rows={data.up} figures={figures} />
          <Side title={t("today.day_down")} rows={data.down} figures={figures} />
        </div>
      ) : null}
      {data.blocks.length ? (
        <div className="td-attr-side">
          <h3 className="td-attr-head">{t("today.day_blocks")}</h3>
          <ul className="td-attr-rows">
            {data.blocks.map((block) => (
              <li
                key={`${block.kind}:${block.label}`}
                className={block.kind === "fund" ? "ag-row-reach" : undefined}
              >
                <BlockName block={block} />
                <span className="td-attr-fig">
                  <strong className={tone(block.amount)}>
                    {figures.money(block.amount)}
                  </strong>
                  <small>{figures.pp(block.pp)}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {data.explained.length ? (
        <ul className="td-lines td-attr-why">
          {data.explained.map((row) => (
            <li key={row.ticker}>
              <TickerCell className="hm-ticker" ticker={row.ticker} name={false} />{" "}
              {t("today.day_explained", {
                pct: figures.pct(row.pct),
                sigmas: row.sigmas,
              })}{" "}
              · <TickerCell className="hm-ticker" ticker={row.etf} name={false} />{" "}
              {figures.pct(row.etf_pct)}: {t(`today.day_verdict_${row.verdict}`)}
            </li>
          ))}
        </ul>
      ) : null}
      {alpha ? (
        <p className="td-attr-note">
          {t("today.day_alpha", {
            index,
            ahead: alpha.ahead,
            sessions: alpha.sessions.length,
          })}{" "}
          <span className={tone(alpha.excess_pp)}>{figures.pp(alpha.excess_pp)}</span>
        </p>
      ) : null}
      {data.stale.length ? (
        <p className="td-attr-note">
          {t("today.day_stale")}
          <span className="td-tks">
            {data.stale.map((ticker) => (
              <TickerCell
                className="hm-ticker"
                key={ticker}
                ticker={ticker}
                name={false}
              />
            ))}
          </span>
        </p>
      ) : null}
      {data.gap ? (
        <p className="td-attr-note">
          {t("today.day_gap", { amount: figures.money(data.gap) })}
        </p>
      ) : null}
    </div>
  );
}
