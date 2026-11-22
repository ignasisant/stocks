/**
 * "Buy the whole sector": the curated UCITS ETFs and mutual funds that hold
 * this sector, beside the companies the page ranks.
 *
 * The podium answers "which of these is the best one"; the obvious next
 * question is "or do I just buy all of them?". Each vehicle is one row of a
 * table, so the figures a reader compares line up down the card: what it
 * costs, how much of it really is the sector, what a euro in it buys, how much
 * of it is this page's cohort, and what it did in the reader's money — from
 * the book's first day first, the year beside it.
 *
 * "What a euro buys" is the card's one drawing: the ten disclosed lines as a
 * bar in weight order, the podium in the accent (as on the podium itself),
 * the page's other names solid, names the page does not rank hatched, the
 * undisclosed rest left empty. The lines themselves sit behind a chevron and
 * mount only when opened (ten logos a fund); the podium names a fund does
 * hold stay on the row, because that overlap is the card's question.
 *
 * Two halves on purpose: `/funds` is the same for everybody and lands at once;
 * `/funds/returns` is the reader's (their currency, their first day) and may
 * need a download, so it fills in under facts that are already on screen.
 *
 * Every overlap is a floor: Yahoo discloses ten lines per fund, so a podium
 * name outside them is "not among its ten largest", never 0 %.
 */

import { Fragment, useId, useState } from "react";

import { get } from "../../shell/api";
import { calendarDay } from "../../shell/dates";
import { percent } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Glyph } from "../../ui/Glyph";
import type {
  FundLine,
  FundReturn,
  SectorFund,
  SectorFundReturns,
  SectorFunds,
} from "./types";

const ROLES: FundLine["role"][] = ["podium", "cohort", "other"];

const share = (value: number, digits = 0) => percent(value, { digits, tight: true });

/**
 * The vehicles, every list always a list. The kept-answers shelf can paint
 * last visit's body, and a body from before `lines` replaced `top` would take
 * the page down at `fund.lines.map`; a missing list reads as empty and the
 * live answer replaces it.
 */
export function readFunds(body: SectorFunds | undefined): SectorFunds {
  return {
    ...body,
    sector: body?.sector ?? "",
    funds: (body?.funds ?? []).map((fund) => ({
      ...fund,
      lines: fund.lines ?? [],
      podium: fund.podium ?? [],
    })),
  };
}

export function Funds({ sector, base }: { sector: string; base: string | undefined }) {
  const t = useT();
  const at = `/sectors/${encodeURIComponent(sector)}/funds`;
  const facts = useApi(() => get<SectorFunds>(at).then(readFunds), [at]);
  const moves = useApi(
    () => get<SectorFundReturns>(`${at}/returns`, base ? { base } : undefined),
    [at, base],
  );
  if (facts.state !== "loaded" || facts.data.funds.length === 0) return null;
  const funds = facts.data.funds;
  const pending = moves.state === "loading";
  const returns = moves.state === "loaded" ? moves.data : null;
  const byTicker = new Map((returns?.returns ?? []).map((r) => [r.ticker, r]));
  const transferFree = returns?.transfer_free ?? false;
  const hasFund = funds.some((f) => f.kind === "fund");
  const hasEtf = funds.some((f) => f.kind === "etf");
  // A guest or an empty book has no first day: the column goes, the year stays.
  const since = returns?.since ?? null;
  const sinceColumn = pending || since !== null;
  return (
    <section className="ag-sec-card" aria-labelledby="ag-sec-funds-h">
      <h2 className="ag-sec-h2" id="ag-sec-funds-h">
        {t("sector.funds_title")}
      </h2>
      <p className="ag-sec-caption">{t("sector.funds_caption")}</p>
      <ul className={`ag-sec-funds${sinceColumn ? "" : " ag-sec-funds-nosince"}`}>
        {/* The header is drawn for the eye; every cell carries its own label
            for a screen reader, and shows it once the rows stack. */}
        <li className="ag-sec-funds-head" aria-hidden="true">
          <span>{t("sector.funds_col_fund")}</span>
          <span className="ag-sec-fund-num">{t("sector.funds_col_ter")}</span>
          <span className="ag-sec-fund-num">{t("sector.funds_col_purity")}</span>
          <span>{t("sector.funds_col_mix")}</span>
          <span className="ag-sec-fund-num">{t("sector.funds_col_cohort")}</span>
          {sinceColumn ? (
            <span className="ag-sec-fund-num">
              {since ? t("sector.funds_col_since", { date: calendarDay(since) }) : null}
            </span>
          ) : null}
          <span className="ag-sec-fund-num">{t("sector.funds_col_y1")}</span>
          <span />
        </li>
        {funds.map((fund) => (
          <FundRow
            key={fund.ticker}
            fund={fund}
            move={byTicker.get(fund.ticker) ?? null}
            pending={pending}
            since={since}
            sinceColumn={sinceColumn}
            transferFree={transferFree && fund.kind === "fund"}
          />
        ))}
      </ul>
      <ul className="ag-sec-mix-legend">
        {ROLES.map((role) => (
          <li key={role}>
            <i className={`ag-sec-mix-sw ag-sec-mix-${role}`} aria-hidden="true" />
            {t(`sector.funds_legend_${role}`)}
          </li>
        ))}
        <li>
          <i className="ag-sec-mix-sw ag-sec-mix-rest" aria-hidden="true" />
          {t("sector.funds_legend_rest")}
        </li>
      </ul>
      <p className="ag-sec-funds-foot">
        {returns
          ? `${
              since
                ? t("sector.funds_in_since", {
                    ccy: returns.currency,
                    date: calendarDay(since),
                  })
                : t("sector.funds_in", { ccy: returns.currency })
            } `
          : null}
        {t("sector.funds_disclosed")}
        {transferFree && hasFund && hasEtf ? ` ${t("sector.funds_etf_taxed")}` : null}
      </p>
    </section>
  );
}

function FundRow({
  fund,
  move,
  pending,
  since,
  sinceColumn,
  transferFree,
}: {
  fund: SectorFund;
  move: FundReturn | null;
  pending: boolean;
  since: string | null;
  sinceColumn: boolean;
  transferFree: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const detail = useId();
  const held = fund.podium.filter((one) => one.weight !== null);
  const ter =
    fund.expense_ratio === null
      ? t("sector.funds_ter_none")
      : t("sector.funds_ter", { pct: share(fund.expense_ratio, 2) });
  return (
    <li className="ag-sec-fund" data-open={open ? "" : undefined}>
      {/* Under a finger the whole block opens the fund, not the 16px symbol. */}
      <div className="ag-sec-fund-who ag-row-reach">
        <span className="ag-sec-fund-line1">
          <TickerCell ticker={fund.ticker} name={false}>
            <b>{fund.ticker}</b>
          </TickerCell>
          {fund.only ? (
            <span className="ag-chip ag-chip-warn">
              {t(`sector.funds_only_${fund.only}`)}
            </span>
          ) : null}
          {transferFree ? (
            <span className="ag-chip ag-chip-up">{t("sector.funds_transfer")}</span>
          ) : null}
        </span>
        <span className="ag-sec-fund-name" title={fund.name}>
          {fund.name}
        </span>
      </div>

      {/* Stacked rows read the three facts as one line instead of cells. */}
      <p className="ag-sec-fund-facts">
        {t(`sector.funds_scope_${fund.scope}`)} · {t(`sector.funds_kind_${fund.kind}`)}{" "}
        · {ter}
        <br />
        <span>
          {t("sector.funds_purity", { pct: share(fund.purity) })} ·{" "}
          {t("sector.funds_cohort", { pct: share(fund.cohort_weight) })}
        </span>
      </p>

      <span className="ag-sec-fund-num ag-sec-fund-ter">
        {fund.expense_ratio === null ? (
          <span className="ag-sec-fund-none" title={ter}>
            —<span className="ag-sr">{ter}</span>
          </span>
        ) : (
          <>
            <span className="ag-sr">{t("sector.funds_col_ter")} </span>
            {share(fund.expense_ratio, 2)}
          </>
        )}
      </span>
      <span className="ag-sec-fund-num ag-sec-fund-purity">
        <span className="ag-sr">{t("sector.funds_col_purity")} </span>
        {share(fund.purity)}
      </span>
      <Mix fund={fund} />
      <span className="ag-sec-fund-num ag-sec-fund-cohort">
        <span className="ag-sr">{t("sector.funds_col_cohort")} </span>
        {share(fund.cohort_weight)}
      </span>
      {sinceColumn ? (
        <span className="ag-sec-fund-num ag-sec-fund-since">
          <Since move={move} pending={pending} since={since} />
        </span>
      ) : null}
      <span className="ag-sec-fund-num ag-sec-fund-y1">
        <span className="ag-sec-fund-lab">{t("sector.funds_col_y1")} </span>
        <Move value={move?.y1 ?? null} pending={pending} small />
      </span>
      <button
        type="button"
        className="ag-sec-fund-more"
        aria-expanded={open}
        aria-controls={detail}
        aria-label={t("sector.funds_more", { ticker: fund.ticker })}
        onClick={() => setOpen((was) => !was)}
      >
        <Glyph name="expand" size={20} />
      </button>

      {held.length ? (
        <p className="ag-sec-fund-podium">
          <span className="ag-sec-fund-podium-label">{t("sector.funds_podium")}</span>{" "}
          {held.map((one, index) => (
            <Fragment key={one.ticker}>
              {index ? ", " : null}
              <TickerCell ticker={one.ticker} name={false}>
                {one.ticker}
              </TickerCell>{" "}
              {share(one.weight ?? 0, 1)}
            </Fragment>
          ))}
        </p>
      ) : null}

      <div className="ag-sec-fund-detail" id={detail} hidden={!open}>
        {open ? <Lines fund={fund} /> : null}
      </div>
    </li>
  );
}

/** What a euro in the fund buys, one segment per disclosed line. */
function Mix({ fund }: { fund: SectorFund }) {
  const t = useT();
  const podium = fund.lines
    .filter((line) => line.role === "podium")
    .reduce((sum, line) => sum + line.weight, 0);
  const label = [
    t("sector.funds_mix", {
      top10: share(fund.top10),
      cohort: share(fund.cohort_weight),
    }),
    podium ? t("sector.funds_mix_podium", { pct: share(podium, 1) }) : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span className="ag-sec-mix" role="img" aria-label={label}>
      {fund.lines.map((line) => (
        <i
          key={line.ticker}
          className={`ag-sec-mix-${line.role}`}
          style={{ flex: `${line.weight} 0 0` }}
        />
      ))}
      <i
        className="ag-sec-mix-gap"
        style={{ flex: `${Math.max(0, 1 - fund.top10)} 0 0` }}
      />
    </span>
  );
}

/** The disclosed lines, opened from the chevron. */
function Lines({ fund }: { fund: SectorFund }) {
  const t = useT();
  const outside = fund.podium.filter((one) => one.weight === null);
  // The sentence carries the names as links: split it at its placeholder so
  // each language keeps its own word order around them.
  const [before, after = ""] = t("sector.funds_podium_outside", {
    names: "\u0000",
  }).split("\u0000");
  return (
    <>
      <ul className="ag-sec-fund-lines">
        {fund.lines.map((line) => (
          <li key={line.ticker} className="ag-row-reach">
            <i className={`ag-sec-mix-sw ag-sec-mix-${line.role}`} aria-hidden="true" />
            <TickerCell ticker={line.ticker} name={false}>
              {line.ticker}
            </TickerCell>
            <span className="ag-sec-fund-line-name">{line.name}</span>
            <span className={line.role === "podium" ? "ag-sec-fund-role" : "ag-sr"}>
              {t(`sector.funds_role_${line.role}`)}
            </span>
            <span className="ag-sec-fund-line-weight">{share(line.weight, 1)}</span>
          </li>
        ))}
      </ul>
      <p className="ag-sec-fund-sums">
        {t("sector.funds_sums", { top10: share(fund.top10), top3: share(fund.top3) })}
        {outside.length ? (
          <>
            {" "}
            {before}
            {outside.map((one, index) => (
              <Fragment key={one.ticker}>
                {index ? ", " : null}
                <TickerCell ticker={one.ticker} name={false}>
                  {one.ticker}
                </TickerCell>
              </Fragment>
            ))}
            {after}
          </>
        ) : null}
      </p>
    </>
  );
}

/** The return from the book's first day, or the fund's own first price. */
function Since({
  move,
  pending,
  since,
}: {
  move: FundReturn | null;
  pending: boolean;
  since: string | null;
}) {
  const t = useT();
  const late = Boolean(move?.opens);
  const label = move?.opens
    ? t("sector.funds_since_late", { date: calendarDay(move.opens) })
    : since
      ? t("sector.funds_since", { date: calendarDay(since) })
      : "";
  return (
    <>
      <Move value={move?.since ?? null} pending={pending} />
      {label ? (
        <span
          className={`ag-sec-fund-lab ag-sec-fund-sub${late ? " ag-sec-fund-late" : ""}`}
        >
          {label}
        </span>
      ) : null}
    </>
  );
}

/** One signed move in points, a quiet block while it is worked out, a dash
 *  when there is none. */
function Move({
  value,
  pending,
  small = false,
}: {
  value: number | null;
  pending: boolean;
  small?: boolean;
}) {
  const t = useT();
  if (value === null && pending) {
    return (
      <span className={`ag-sec-fund-sk${small ? " ag-sec-fund-sk-s" : ""}`}>
        <span className="ag-sr">{t("sector.funds_returns_wait")}</span>
      </span>
    );
  }
  if (value === null) {
    return (
      <span className="ag-sec-fund-none">
        —<span className="ag-sr">{t("sector.funds_no_return")}</span>
      </span>
    );
  }
  return (
    <b
      className={`${small ? "ag-sec-fund-y1v" : "ag-sec-fund-ret"} ${
        value < 0 ? "ag-tone-down" : "ag-tone-up"
      }`}
    >
      {percent(value, { digits: 1, signed: true, points: true })}
    </b>
  );
}
