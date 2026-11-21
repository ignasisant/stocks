/**
 * The market in one strip: what happened today, this week or this month, for
 * a reader who came to look at their own book.
 *
 * The Pulse compressed rather than repeated. The regime chip is the Pulse's
 * own composite and band; the tiles are series the Pulse already downloads
 * (`GET /home/market` never widens its burst), each with the move over the
 * chosen window and an arrow for the trend it sits in. Everything else — why
 * the score is where it is, the gauges, the rotation — stays one link away.
 *
 * The window is remembered per browser: it is a way of reading the page, not
 * an account setting worth a write.
 *
 * A move is coloured by what it means for somebody long equities, not by its
 * sign: the VIX or a yield rising is red. A tile with no side to take (a
 * currency pair, gold, oil) stays grey.
 */

import { useState, type ReactNode } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useTabStrip } from "../../shell/useTabStrip";
import { Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Help, type Tone } from "../../ui/Kpi";
import { Card, CardQuery, CardTitle, Note } from "./ui";
import { Segmented } from "../../ui/Segmented";
import { plain, shortDate } from "./format";
import type { MarketGlance, MarketTile, MarketWindow } from "./types";
import { decimal, money, percent } from "../../shell/format";

const WINDOWS: { key: MarketWindow; label: string }[] = [
  { key: "day", label: "home.market_window_day" },
  { key: "week", label: "home.market_window_week" },
  { key: "month", label: "home.market_window_month" },
];

const REMEMBER = "hm.market.window";

/** Spelled out so the catalog keys are greppable. */
const LABELS: Record<string, string> = {
  sp500: "home.market_tile_sp500",
  nasdaq: "home.market_tile_nasdaq",
  stoxx50: "home.market_tile_stoxx50",
  ibex: "home.market_tile_ibex",
  em: "home.market_tile_em",
  vix: "home.market_tile_vix",
  us10y: "home.market_tile_us10y",
  eurusd: "home.market_tile_eurusd",
  gold: "home.market_tile_gold",
  oil: "home.market_tile_oil",
  btc: "home.market_tile_btc",
};

const ARROWS: Record<string, { glyph: string; label: string; tone: Tone }> = {
  up: { glyph: "↑", label: "sentiment.state_up", tone: "up" },
  turning_up: { glyph: "↗", label: "sentiment.state_turning_up", tone: "flat" },
  turning_down: { glyph: "↘", label: "sentiment.state_turning_down", tone: "flat" },
  down: { glyph: "↓", label: "sentiment.state_down", tone: "down" },
};

const REGIME_TONES: Record<string, string> = {
  stress: "hm-regime-down",
  caution: "hm-regime-warn",
  neutral: "hm-regime-flat",
  appetite: "hm-regime-up",
  euphoria: "hm-regime-warn",
};

function remembered(): MarketWindow {
  try {
    const value = window.localStorage.getItem(REMEMBER);
    if (value === "day" || value === "week" || value === "month") return value;
  } catch {
    // Storage blocked: the default is a fine answer.
  }
  return "day";
}

function remember(value: MarketWindow): void {
  try {
    window.localStorage.setItem(REMEMBER, value);
  } catch {
    // Not worth an error: the choice holds for this visit either way.
  }
}

export function MarketCard({ nonce }: { nonce: number }) {
  const t = useT();
  const query = useApi<MarketGlance>(() => get<MarketGlance>("/home/market"), [nonce]);
  return (
    <CardQuery
      query={query}
      note={t("home.market_unavailable")}
      title={plain(t("home.market_title"))}
      skeleton={<Skeleton rows={2} />}
    >
      {(data) => <Market data={data} />}
    </CardQuery>
  );
}

export function Market({ data }: { data: MarketGlance }) {
  const t = useT();
  const lang = useLang();
  const [range, setRange] = useState<MarketWindow>(remembered);
  const pick = (key: MarketWindow) => {
    setRange(key);
    remember(key);
  };
  // `?? []`: a body without the list was once painted from the kept shelf
  // and took the whole Home down with it; an empty strip is the honest read.
  const tiles = (data.tiles ?? []).filter((tile) => LABELS[tile.key]);
  return (
    <Card className="hm-market">
      {/* The head every card with a range draws: title, the picker beside it.
          The way out to the Pulse closes the card, as on the others. */}
      <div className="hm-card-head">
        <CardTitle>{plain(t("home.market_title"))}</CardTitle>
        <Segmented
          label={t("home.market_range")}
          items={WINDOWS.map(({ key, label }) => ({ id: key, label: t(label) }))}
          value={range}
          onPick={pick}
        />
      </div>
      <Regime data={data} />
      {tiles.length === 0 ? (
        <Note>{t("home.market_unavailable")}</Note>
      ) : (
        <Strip>
          {tiles.map((tile) => (
            <li key={tile.key}>
              <Tile tile={tile} range={range} />
            </li>
          ))}
        </Strip>
      )}
      {data.breadth || data.as_of ? (
        <p className="hm-caption">
          {[
            data.breadth
              ? t("home.market_breadth", {
                  hits: data.breadth.hits,
                  total: data.breadth.total,
                  window: data.breadth.window,
                })
              : null,
            tiles.some((tile) => tile.state) ? t("home.market_arrow_key") : null,
            data.as_of
              ? t("home.market_as_of", { date: shortDate(data.as_of, lang) })
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      <Link page="sentiment" className="hm-link">
        {t("home.market_link_pulse")}
      </Link>
    </Card>
  );
}

/** The Pulse's composite as a chip: score, band, the week's move, its path. */
function Regime({ data }: { data: MarketGlance }) {
  const t = useT();
  const lang = useLang();
  if (data.score === null) return null;
  const band = REGIME_TONES[data.regime] ? data.regime : "unknown";
  // `?? []`, as for the tiles: a body without the list costs the week, not the Home.
  const history = data.history ?? [];
  const last = history.at(-1);
  const before = history.at(-6);
  const week = last !== undefined && before !== undefined ? last - before : null;
  const run = data.run ? t("sentiment.regime_run", { n: data.run }) : null;
  return (
    <span className={`hm-regime ${REGIME_TONES[band] ?? "hm-regime-flat"}`}>
      <Gauge value={data.score} />
      <span className="hm-regime-body">
        <strong>{Math.round(data.score)}</strong>
        <span className="hm-regime-label">{t("home.market_regime_label")}</span>
        <span>{t(`sentiment.regime_${band}`)}</span>
        {week !== null ? (
          <span className="hm-regime-delta">
            {t("home.market_regime_delta", {
              delta: decimal(week, { lang, digits: 0, signed: "always" }) ?? "",
            })}
          </span>
        ) : null}
        <Help text={[t("home.market_regime_help"), run].filter(Boolean).join(" · ")} />
      </span>
    </span>
  );
}

/** The composite on its fixed 0-100 scale as a half dial: track, arc to the score, a dot at its end. */
function Gauge({ value }: { value: number }) {
  const share = Math.max(0, Math.min(100, value)) / 100;
  const angle = Math.PI * (1 - share);
  const x = 42 + 34 * Math.cos(angle);
  const y = 44 - 34 * Math.sin(angle);
  return (
    <svg
      className="hm-gauge"
      viewBox="0 0 84 48"
      width={84}
      height={48}
      aria-hidden="true"
    >
      <path className="hm-gauge-track" d="M8 44a34 34 0 0 1 68 0" />
      {share > 0 ? (
        <path
          className="hm-gauge-arc"
          d={`M8 44A34 34 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`}
        />
      ) : null}
      <circle className="hm-gauge-dot" cx={x.toFixed(1)} cy={y.toFixed(1)} r={4.5} />
    </svg>
  );
}

/** A tile's recent levels as a line, scaled to its own range; null when too short to read. */
function TileSpark({ values, tone }: { values: number[]; tone: Tone }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * 44;
      const y = 16 - ((v - lo) / (hi - lo || 1)) * 14;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className={`hm-mtile-spark hm-tone-${tone}`}
      viewBox="0 0 44 18"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline points={points} />
    </svg>
  );
}

function moveTone(change: number | undefined, welcome: number): Tone {
  if (change === undefined || change === 0 || welcome === 0) return "flat";
  return change * welcome > 0 ? "up" : "down";
}

/**
 * The tiles' row. On a phone it scrolls sideways, and the edge with more past
 * it fades, so "Emerging" cut at the border reads as "there is more" rather
 * than as a clipped tile. Its own component so the hook mounts with the row.
 */
function Strip({ children }: { children: ReactNode }) {
  return (
    <ul className="hm-market-strip ag-fade-x" ref={useTabStrip<HTMLUListElement>("")}>
      {children}
    </ul>
  );
}

function Tile({ tile, range }: { tile: MarketTile; range: MarketWindow }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  const change = tile.changes[range];
  const moved =
    change === undefined
      ? null
      : tile.unit === "basis_points"
        ? t("home.market_bp", {
            n: decimal(change, { lang, digits: 0, signed: "always" }) ?? "",
          })
        : percent(change, { lang, signed: "always", digits: 1 });
  const arrow = tile.state ? ARROWS[tile.state] : undefined;
  const body = (
    <>
      <span className="hm-mtile-label">{t(LABELS[tile.key] ?? tile.key)}</span>
      <span className="hm-mtile-value">{level(tile, lang) ?? na}</span>
      <TileSpark values={tile.spark ?? []} tone={moveTone(change, tile.welcome)} />
      <span className="hm-mtile-move">
        <span className={`hm-mtile-change hm-tone-${moveTone(change, tile.welcome)}`}>
          {moved ?? na}
        </span>
        {arrow ? (
          <span
            className={`hm-mtile-arrow hm-tone-${arrow.tone}`}
            title={t(arrow.label)}
            role="img"
            aria-label={t(arrow.label)}
          >
            {arrow.glyph}
          </span>
        ) : null}
      </span>
      {tile.percentile !== null ? (
        <span className="hm-mtile-sub">{vixWord(tile.percentile, t)}</span>
      ) : null}
    </>
  );
  // Every symbol opens its own page; a FRED series has none to open.
  return tile.linkable ? (
    <Link
      page="ticker"
      params={{ ticker: tile.symbol }}
      className="hm-mtile"
      title={tile.symbol}
    >
      {body}
    </Link>
  ) : (
    <div className="hm-mtile">{body}</div>
  );
}

/** The level in the unit a reader quotes it in. */
function level(tile: MarketTile, lang: string): string | null {
  const value = tile.value;
  if (value === null) return null;
  if (tile.unit === "basis_points") return percent(value / 100, { lang, digits: 2 });
  if (tile.group === "fx") return decimal(value, { lang, digits: 4 });
  if (tile.group === "commodity" || tile.group === "crypto") {
    return money(value, { currency: "USD", lang, digits: value >= 1000 ? 0 : 2 });
  }
  return decimal(value, { lang, digits: value >= 1000 ? 0 : 2 });
}

/** Where the fear gauge sits in its own year: a word, then the share of the year's days it is above. */
function vixWord(
  pct: number,
  t: (key: string, slots?: Record<string, string | number>) => string,
): string {
  const word =
    pct < 33
      ? t("home.market_vix_low")
      : pct > 66
        ? t("home.market_vix_high")
        : t("home.market_vix_normal");
  return t("home.market_vix_pct", { label: word, n: Math.round(pct) });
}
