/**
 * The market read every account shares: macro and trends.
 *
 * Written once a morning for everyone (`chat/today_market.py`): the figures
 * are computed — yields, the Fed and the ECB with the days to their next
 * decision, inflation in the US and the euro area, the risk-appetite regime,
 * how many sectors hold their long average, which lead and which trail the
 * S&P 500 over the month, crypto sentiment — and, when the model wrote the
 * read, a few lines on what they mean (a computed read's lines only repeat
 * the tiles, so they are not drawn). Each tile stands on its own, so a source
 * that did not answer costs a tile and never the section.
 *
 * Rates are a level, not a move to cheer: their monthly change is a grey
 * chip, never green or red.
 */

import type { ReactNode } from "react";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Kpi, KpiGrid, type ChipSpec } from "../../ui/Kpi";
import { decimal, monthDay, percent, type Translate } from "../home/format";
import { TickerCell } from "../home/ui";
import { leadersLaggards, marketSplit } from "./card";
import type { MarketCard, MarketLine, MarketSector } from "./types";

/** A change in basis points as a grey chip: "+8 bp". */
function bpChip(bp: number | null, lang: string, t: Translate): ChipSpec | null {
  if (bp === null || !Number.isFinite(bp)) return null;
  const text = decimal(bp, lang, 0, { signed: true });
  return text ? { text: t("today.bp", { value: text }), tone: "flat" } : null;
}

/** The model's read of the figures above it: a voice, set apart from them. */
function Written({ lines }: { lines: MarketLine[] }) {
  if (!lines.length) return null;
  return (
    <ul className="td-lines td-voice">
      {lines.map((line, n) => (
        <li key={n}>{line.line}</li>
      ))}
    </ul>
  );
}

/** Rates, central banks and inflation. */
export function Macro({ market }: { market: MarketCard }) {
  const t = useT();
  const lang = useLang();
  const { macro } = marketSplit(market);
  // A policy rate is the bank's own tile when the bank is there.
  const banks = new Set(market.banks.map((bank) => `policy_${bank.bank}`));
  const rates = market.rates.filter((rate) => !banks.has(rate.key));
  const level = (value: number | null) =>
    value === null ? t("home.na") : `${decimal(value, lang, 2) ?? ""}%`;

  const tiles: ReactNode[] = [
    ...rates.map((rate) => (
      <Kpi
        key={rate.key}
        label={t(`today.rate_${rate.key}`)}
        value={
          rate.key === "curve_2s10s"
            ? t("today.bp", {
                value: decimal(rate.value * 100, lang, 0, { signed: true }) ?? "",
              })
            : level(rate.value)
        }
        chip={bpChip(rate.change_bp, lang, t)}
      />
    )),
    ...market.banks.map((bank) => {
      const next = monthDay(bank.next_date, t);
      const note =
        bank.days === 0
          ? t("today.bank_today")
          : bank.days !== null && next
            ? t("today.bank_next", { days: bank.days, date: next })
            : null;
      return (
        <Kpi
          key={bank.bank}
          label={t(`today.bank_${bank.bank}`)}
          value={level(bank.rate)}
          chip={bpChip(bank.last_move_bp, lang, t)}
          note={note}
        />
      );
    }),
    ...market.inflation.map((row) => (
      <Kpi
        key={row.area}
        label={t(`today.area_${row.area.toLowerCase()}`)}
        value={level(row.headline)}
        note={
          row.core === null
            ? row.period
            : t("today.core", { value: level(row.core), period: row.period })
        }
      />
    )),
  ];

  return (
    <>
      {tiles.length ? <KpiGrid>{tiles}</KpiGrid> : null}
      <Written lines={macro} />
    </>
  );
}

function SectorList({ title, sectors }: { title: string; sectors: MarketSector[] }) {
  const t = useT();
  const lang = useLang();
  if (!sectors.length) return null;
  return (
    <div className="td-sectors">
      <h3 className="td-sub">{title}</h3>
      <ul>
        {sectors.map((sector) => {
          const month = sector.month ?? 0;
          return (
            <li key={sector.ticker}>
              <TickerCell ticker={sector.ticker} name={false} />
              <span className="td-sector-name">
                {t(`sentiment.sector_${sector.name.toLowerCase().replace(/ /g, "_")}`)}
              </span>
              <span className={`hm-num ${month < 0 ? "td-down" : "td-up"}`}>
                {t("today.pp", {
                  value: decimal(month, lang, 1, { signed: true }) ?? "",
                })}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The regime, breadth, sector rotation and crypto. */
export function Trends({ market }: { market: MarketCard }) {
  const t = useT();
  const lang = useLang();
  const { trends } = marketSplit(market);
  const { leaders, laggards } = leadersLaggards(market.sectors);
  const { regime, breadth, crypto } = market;

  const tiles: ReactNode[] = [];
  if (regime)
    tiles.push(
      <Kpi
        key="regime"
        label={t("today.regime")}
        value={t(`sentiment.regime_${regime.key}`)}
        note={t("today.regime_note", {
          score: Math.round(regime.score),
          run: regime.run,
        })}
        help={t("today.regime_help")}
      />,
    );
  if (breadth && breadth.sectors_total)
    tiles.push(
      <Kpi
        key="breadth"
        label={t("today.breadth")}
        value={`${breadth.sectors_hits}/${breadth.sectors_total}`}
        note={t("today.breadth_note")}
      />,
    );
  if (crypto?.fear_greed !== null && crypto?.fear_greed !== undefined)
    tiles.push(
      <Kpi
        key="fg"
        label={t("today.fear_greed")}
        value={String(Math.round(crypto.fear_greed))}
        note={
          crypto.fear_greed_week === null
            ? null
            : t("today.fear_greed_week", { value: Math.round(crypto.fear_greed_week) })
        }
      />,
    );
  if (crypto?.btc_dominance !== null && crypto?.btc_dominance !== undefined)
    tiles.push(
      <Kpi
        key="btc"
        label={t("today.btc_dom")}
        value={percent(crypto.btc_dominance / 100, lang, { digits: 1 }) ?? t("home.na")}
      />,
    );

  return (
    <>
      {tiles.length ? <KpiGrid>{tiles}</KpiGrid> : null}
      {leaders.length ? (
        <div className="td-rotation">
          <SectorList title={t("today.leaders")} sectors={leaders} />
          <SectorList title={t("today.laggards")} sectors={laggards} />
        </div>
      ) : null}
      <Written lines={trends} />
      <Link page="sentiment" className="td-more">
        {t("today.open_pulse")}
      </Link>
    </>
  );
}
