/**
 * Against the index: this listing's line beside the ones the reader measures
 * it by, all rebased to the window's first day and all in their own money.
 *
 * Two price charts side by side cannot say "did it beat the S&P": each sits on
 * its own scale and in its own currency. Here every line is the same thing —
 * the total return of one euro (or whatever the account reports in) put in on
 * the first day — so the answer is which line ends higher.
 *
 * It opens on what one name answers to: SPY, the sector's ETF and a few of
 * Yahoo's related names, picked by the server (`?with=` omitted). The rest of
 * the related names sit beside them as chips, and the search adds anything
 * else — QQQ or EEM included; six lines beside the subject at most, past
 * which the legend outgrows the chart.
 */

import { useEffect, useRef, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { chart } from "../../shell/theme";
import { ToggleChip } from "../../ui/Toggle";
import { ReturnLines, type ReturnSeries } from "../portfolio/charts";
import { maybe, sectorKey } from "../sentiment/format";
import { getCompare, searchTickers } from "./data";
import { signedPercent } from "./format";
import { ChipMark } from "./Peers";
import { Card, Note, Segmented } from "./ui";
import type { CompareLine, CompareOffer, Comparison, SearchMatch } from "./types";
// The chart and its legend are styled with the portfolio's, as the chat's are.
import "../portfolio/portfolio.css";

const COMPARE_RANGES = ["1m", "6m", "1y", "2y"] as const;
export type CompareRange = (typeof COMPARE_RANGES)[number];

/** Lines beside the subject — `analysis.compare.MAX_OTHERS`. */
const MAX_OTHERS = 6;

const DEBOUNCE_MS = 160;

/**
 * A colour per drawn name. The indices keep the hues the risk tab draws them
 * in, so SPY reads as SPY on both pages; everything else takes the next free
 * one in the order it was added.
 */
export function lineColors(
  selected: readonly string[],
  palette: ReturnType<typeof chart>,
): Record<string, string> {
  const fixed: Record<string, string> = {
    SPY: palette.info,
    QQQ: palette.warn,
    EEM: palette.warnOrange,
  };
  const rest = [
    palette.brandAccent,
    palette.candleUp,
    palette.candleDown,
    palette.smaLong,
    palette.smaFast,
    palette.smaSlow,
  ];
  const out: Record<string, string> = {};
  let next = 0;
  for (const name of selected) {
    out[name] = fixed[name] ?? rest[next++ % rest.length]!;
  }
  return out;
}

export function CompareSection({ ticker, base }: { ticker: string; base: string }) {
  const t = useT();
  const lang = useLang();
  const [range, setRange] = useState<CompareRange>("1y");
  // Null until a chip is pressed: the server's opening lines.
  const [picked, setPicked] = useState<string[] | null>(null);
  const query = useApi(
    () => getCompare(ticker, range, base, picked ?? undefined),
    [ticker, range, base, picked?.join(",") ?? null],
  );
  // The chips outlive a reload: a new range or pick must not blank the very
  // controls the reader just pressed.
  const offered = useRef<CompareOffer[]>([]);
  // …and so does the chart: the last answer stays up, dimmed, until the next
  // lands, rather than the card dropping to a skeleton on every chip.
  const last = useRef<Comparison | null>(null);
  if (query.state === "loaded") {
    offered.current = query.data.offered;
    last.current = query.data;
  }
  const selected =
    picked ??
    (last.current?.lines ?? [])
      .filter((line) => line.role !== "subject")
      .map((line) => line.ticker);

  const palette = chart();
  const colors = lineColors(selected, palette);
  const full = selected.length >= MAX_OTHERS;

  const toggle = (name: string) =>
    setPicked(
      selected.includes(name)
        ? selected.filter((one) => one !== name)
        : selected.length >= MAX_OTHERS
          ? selected
          : [...selected, name],
    );

  const date = new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" });
  const yearly = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) =>
    (range === "1m" || range === "6m" ? date : yearly).format(
      new Date(`${iso}T00:00:00`),
    );

  const labelOf = (
    line: Pick<CompareLine, "ticker" | "role">,
    sector?: string | null,
  ) =>
    line.role === "index"
      ? (maybe(t, `portfolio.bench_${line.ticker.toLowerCase()}`) ?? line.ticker)
      : line.role === "sector" && sector
        ? t("ticker.compare_sector", {
            sector: maybe(t, `sentiment.sector_${sectorKey(sector)}`) ?? sector,
          })
        : line.ticker;
  const sectorName = offered.current.find((one) => one.role === "sector")?.sector;

  const offeredNames = new Set(offered.current.map((one) => one.ticker));
  const picks = selected.filter((name) => !offeredNames.has(name));

  return (
    <Card
      fold="compare"
      title={t("ticker.compare")}
      note={t("ticker.compare_note", { base })}
    >
      <div className="tk-compare-controls">
        <Segmented
          label={t("ticker.period")}
          options={COMPARE_RANGES}
          value={range}
          onChange={setRange}
          format={(one) => t(`ticker.period_${one}`)}
        />
      </div>

      <div className="tk-chips tk-compare-chips">
        {offered.current.map((offer) => {
          const on = selected.includes(offer.ticker);
          return (
            <ToggleChip
              key={offer.ticker}
              on={on}
              disabled={!on && full}
              title={offer.name || undefined}
              onClick={() => toggle(offer.ticker)}
            >
              {on ? <Swatch color={colors[offer.ticker]} /> : null}
              {offer.role === "index" ? null : <ChipMark ticker={offer.ticker} />}
              {labelOf(offer, offer.sector)}
            </ToggleChip>
          );
        })}
        {picks.map((name) => (
          <ToggleChip
            key={name}
            on
            title={t("ticker.compare_drop")}
            onClick={() => toggle(name)}
          >
            <Swatch color={colors[name]} />
            <ChipMark ticker={name} />
            {name} <span aria-hidden="true">×</span>
          </ToggleChip>
        ))}
      </div>

      <PickSearch
        ticker={ticker}
        selected={selected}
        full={full}
        onPick={(name) => toggle(name)}
      />

      {query.state === "loading" && last.current ? (
        <div className="tk-compare-stale" aria-busy="true">
          <CompareChart
            data={last.current}
            colors={colors}
            label={(line) => labelOf(line, sectorName)}
            formatDate={formatDate}
          />
        </div>
      ) : (
        <Loaded
          query={query}
          skeleton={
            <div className="tk-compare-wait">
              <Skeleton rows={6} />
            </div>
          }
        >
          {(data) => (
            <CompareChart
              data={data}
              colors={colors}
              label={(line) => labelOf(line, sectorName)}
              formatDate={formatDate}
            />
          )}
        </Loaded>
      )}
    </Card>
  );
}

export function CompareChart({
  data,
  colors,
  label,
  formatDate,
}: {
  data: Comparison;
  colors: Record<string, string>;
  label: (line: CompareLine) => string;
  formatDate: (iso: string) => string;
}) {
  const t = useT();
  const palette = chart();
  if (data.dates.length < 2) return <Note>{t("ticker.history_empty")}</Note>;
  const series: ReturnSeries[] = data.lines.map((line) =>
    line.role === "subject"
      ? {
          label: line.ticker,
          points: line.points,
          color: palette.textPrimary,
          focal: true,
        }
      : {
          label: label(line),
          points: line.points,
          color: colors[line.ticker] ?? palette.textMuted,
        },
  );
  return (
    <>
      <ReturnLines
        dates={data.dates}
        series={series}
        label={t("ticker.compare_chart", { ticker: data.ticker })}
        format={(value) => signedPercent(value, 1)}
        tickFormat={(value) => signedPercent(value, 0)}
        formatDate={formatDate}
        legendValues
      />
      {data.missing.length > 0 ? (
        <Note>{t("ticker.compare_missing", { names: data.missing.join(", ") })}</Note>
      ) : null}
    </>
  );
}

/** The line's hue on its chip, so a chip and its line read as one thing. */
function Swatch({ color }: { color: string | undefined }) {
  return color ? (
    <span
      className="tk-compare-swatch"
      style={{ background: color }}
      aria-hidden="true"
    />
  ) : null;
}

/** Any other listing, by symbol or name. */
function PickSearch({
  ticker,
  selected,
  full,
  onPick,
}: {
  ticker: string;
  selected: readonly string[];
  full: boolean;
  onPick: (name: string) => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchMatch[] | null>(null);
  const trimmed = query.trim();

  useEffect(() => {
    if (!trimmed) {
      setHits(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      searchTickers(trimmed, 6)
        .then((body) => live && setHits(body.matches))
        .catch(() => live && setHits([]));
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [trimmed]);

  const offers = (hits ?? []).filter(
    (match) => match.ticker !== ticker && !selected.includes(match.ticker),
  );

  return (
    <div className="tk-peers-group">
      <input
        className="tk-field"
        type="text"
        autoComplete="off"
        aria-label={t("ticker.compare_add")}
        placeholder={full ? t("ticker.compare_full") : t("ticker.compare_add")}
        disabled={full}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {offers.length > 0 ? (
        <div className="tk-chips">
          {offers.map((match) => (
            <ToggleChip
              key={match.ticker}
              on={false}
              onClick={() => {
                onPick(match.ticker);
                setQuery("");
                setHits(null);
              }}
            >
              <ChipMark ticker={match.ticker} />
              {match.ticker}
              {match.name ? <span className="tk-chip-name">{match.name}</span> : null}
            </ToggleChip>
          ))}
        </div>
      ) : null}
      {trimmed !== "" && hits !== null && offers.length === 0 ? (
        <Note>{t("ticker.extra_none")}</Note>
      ) : null}
    </div>
  );
}
