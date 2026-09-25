/**
 * Five seconds: the composite score, the band it is in, how long it has held
 * it — and, beside it, the same regime restated as what it does to the
 * reader's own basket.
 *
 * The two halves arrive from two endpoints and are drawn independently, which
 * is the honest thing to do: the composite needs no account and the personal
 * half needs a ledger replay, so half-loaded is a real state and the layout
 * draws it rather than holding the score back for the slower side.
 */

import type { ReactNode } from "react";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { DownBody } from "./Down";
import { HeroSpark } from "./Spark";
import { NA, fixed, percent, share, signed } from "./format";
import type { Pulse, PulseBook } from "./types";

/** The bands the catalogs have a pill for. Anything else reads as "no reading". */
const REGIMES = new Set([
  "stress",
  "caution",
  "neutral",
  "appetite",
  "euphoria",
  "unknown",
]);

/** Horizons the score deltas are quoted over, in sessions — the page's own set. */
const WEEK = 5;
const MONTH = 21;

function regimeKey(regime: string): string {
  return REGIMES.has(regime) ? regime : "unknown";
}

/**
 * The "and where it was" pill that rides every personalised figure.
 *
 * A beta of 1.05 is unremarkable; a beta that was 0.82 a quarter ago means the
 * book got materially more market-sensitive without the reader buying
 * anything, because the regime moved under it. So the pill is the drift of the
 * rolling statistic against its own past value — never against the
 * full-window headline beside it, which is a different window and whose
 * difference would not be drift at all.
 */
export function DriftPill({ now, then }: { now: number | null; then: number | null }) {
  const t = useT();
  if (now === null || then === null) return null;
  // A 0.02 wobble on a rolling statistic is noise, so the pill stays neutral
  // until the move is big enough to be worth a reader's attention.
  const moved = Math.abs(now - then) >= 0.05;
  return (
    <span className={`sn-pill ${moved ? "sn-pill-warn" : "sn-pill-flat"}`}>
      {t("sentiment.drift_pill", { value: then.toFixed(2) })}
    </span>
  );
}

/**
 * The composite: score, band, run, its own 90 sessions, and what it is missing.
 *
 * A composite nobody could build (`unavailable`) keeps the kicker and says why
 * instead of drawing a meter parked at "n/a" — a pin with no score under it
 * reads as a market that is neutral, not as a feed that is down.
 */
export function Composite({ pulse, onRetry }: { pulse: Pulse; onRetry?: () => void }) {
  const t = useT();
  if (pulse.unavailable) {
    return (
      <div className="sn-pulse">
        <div className="sn-kicker">{t("sentiment.kicker_pulse")}</div>
        <DownBody reason={pulse.unavailable} onRetry={onRetry} />
      </div>
    );
  }
  const band = regimeKey(pulse.regime);
  const scores = pulse.history.map((point) => point.score);

  const delta = (ago: number): number | null => {
    if (scores.length <= ago) return null;
    const last = scores[scores.length - 1];
    const before = scores[scores.length - 1 - ago];
    return last === undefined || before === undefined ? null : last - before;
  };
  const deltas: [string, number | null][] = [
    ["week", delta(WEEK)],
    ["month", delta(MONTH)],
  ];

  // The pin sits at the score's own position on the 0-100 track. A score that
  // could not be built parks it mid-scale under an "n/a" headline, on a flat
  // track: at zero it would read as maximum fear, which is a claim nobody made.
  const known = pulse.score !== null;
  const pin = pulse.score === null ? 50 : Math.max(0, Math.min(100, pulse.score));
  const monthAgo = delta(MONTH);
  const ghost =
    known && monthAgo !== null ? Math.max(0, Math.min(100, pin - monthAgo)) : null;

  const lo = scores.length ? Math.min(...scores) : null;
  const hi = scores.length ? Math.max(...scores) : null;

  return (
    <div className="sn-pulse">
      <div className="sn-kicker">{t("sentiment.kicker_pulse")}</div>
      <div className="sn-pulse-head">
        <span className="sn-pulse-score">{known ? fixed(pulse.score, 0) : NA}</span>
        <span className="sn-pulse-band">
          <span className={`sn-pill sn-pill-lg sn-regime-${band}`}>
            {t(`sentiment.regime_${band}`)}
          </span>
          {pulse.run > 0 && (
            <span className="sn-pulse-run">
              {t("sentiment.regime_run", { n: pulse.run })}
            </span>
          )}
        </span>
        <span className="sn-pulse-deltas">
          <span className="sn-pulse-chips">
            {deltas.map(([name, value]) =>
              value === null ? null : (
                <span className="sn-delta" key={name}>
                  <i>{t(`sentiment.h_${name}`)}</i>
                  <b
                    className={value > 0 ? "sn-good" : value < 0 ? "sn-bad" : "sn-flat"}
                  >
                    {signed(value, 1)}
                  </b>
                </span>
              ),
            )}
          </span>
          <span className="sn-mono">{t("sentiment.delta_unit")}</span>
        </span>
      </div>

      <div className={`sn-meter${known ? "" : " sn-meter-flat"}`}>
        {ghost !== null && (
          <div className="sn-meter-ghost" style={{ left: `calc(${ghost}% - 1px)` }} />
        )}
        <div className="sn-meter-pin" style={{ left: `calc(${pin}% - 2.5px)` }} />
      </div>
      <div className="sn-meter-scale">
        <span>0 {t("sentiment.regime_stress").toUpperCase()}</span>
        <span>20</span>
        <span>40 {t("sentiment.regime_neutral").toUpperCase()} 60</span>
        <span>80</span>
        <span>{t("sentiment.regime_euphoria").toUpperCase()} 100</span>
      </div>
      <p className="sn-help">{t("sentiment.pulse_help")}</p>

      {scores.length > 1 && (
        <div className="sn-sparkbox">
          <div className="sn-sparkbox-l">
            <span>{t("sentiment.spark_window", { n: scores.length })}</span>
            <span>
              {t("sentiment.spark_range", {
                lo: fixed(lo, 0),
                hi: fixed(hi, 0),
              })}
            </span>
          </div>
          <HeroSpark values={scores} />
          <div className="sn-sparkbox-y">
            <span>80</span>
            <span>50</span>
            <span>20</span>
          </div>
        </div>
      )}

      <span className="sn-mono">
        {t("sentiment.pulse_stamp", {
          date: pulse.as_of ?? NA,
          live: pulse.components.length,
          total: pulse.components.length + pulse.missing.length,
        })}
      </span>
    </div>
  );
}

/** One line of the personal panel: what it is, what it reads, where it was. */
function SideRow({
  label,
  value,
  pill,
}: {
  label: string;
  value: string;
  pill?: ReactNode;
}) {
  return (
    <div className="sn-srow">
      <span className="sn-srow-l">{label}</span>
      <span className="sn-srow-v">{value}</span>
      {pill}
    </div>
  );
}

/**
 * The hero's right half: this regime, restated as what it does here.
 *
 * Three figures, chosen because they are the ones a reader can act on — how
 * much of the index's move lands on their basket, whether their bonds are
 * still hedging their equities, and how much of their value is priced in a
 * currency they do not spend. There is no honest version of this panel for an
 * empty ledger, so an empty book says what it would show instead of inventing
 * a beta of 1.00 and a dollar share of zero.
 */
export function Side({
  book,
  regime,
  onRetry,
}: {
  book: PulseBook;
  regime: string;
  onRetry?: () => void;
}) {
  const t = useT();
  const empty =
    book.beta === null &&
    book.usd_share === null &&
    Object.keys(book.currency_weights).length === 0;

  // Empty because the replay could not be priced is not an empty ledger: the
  // invitation to import would be telling a holder they hold nothing.
  if (empty && book.unavailable) {
    return (
      <div className="sn-side">
        <div className="sn-kicker sn-kicker-own">
          {t("sentiment.side_kicker")}
          <span className="sn-spacer" />
          <span className="sn-mono">{t("sentiment.src_book")}</span>
        </div>
        <DownBody reason={book.unavailable} onRetry={onRetry} />
      </div>
    );
  }

  if (empty) {
    return (
      <div className="sn-side">
        <div className="sn-kicker sn-kicker-own">{t("sentiment.side_kicker")}</div>
        <div className="sn-invite">
          <p>{t("sentiment.book_empty")}</p>
          <span className="sn-help">{t("sentiment.book_empty_note")}</span>
          <Link page="import" className="sn-cta">
            {t("sentiment.book_import_cta")}
          </Link>
        </div>
      </div>
    );
  }

  const drag = book.fx_drag;
  return (
    <div className="sn-side">
      <div className="sn-kicker sn-kicker-own">
        {t("sentiment.side_kicker")}
        <span className="sn-badge">{t("sentiment.side_badge")}</span>
        <span className="sn-spacer" />
        {/* Where these three figures come from, in the panel that makes the
            page's least checkable claims: a beta and a correlation are two
            series regressed against each other, and a reader who is not told
            which two is being asked to take them. */}
        <span className="sn-mono">{t("sentiment.src_book")}</span>
      </div>
      {/* The sentence is the point of the panel: a number a reader has to
          interpret is a number most readers will not. It needs a stance, and a
          stance needs a beta, so a book with neither gets the rows alone. */}
      {book.stance !== null && (
        <p className="sn-lede">
          {t("sentiment.side_lede", {
            regime: t(`sentiment.regime_${regimeKey(regime)}`),
            stance: t(`sentiment.stance_${book.stance}`),
            beta: fixed(book.beta, 2),
            usd: share(book.usd_share),
          })}
        </p>
      )}
      <SideRow
        label={t("sentiment.beta_equity")}
        value={fixed(book.beta, 2)}
        pill={<DriftPill now={book.beta_rolling} then={book.beta_rolling_then} />}
      />
      {book.bond_correlation !== null && (
        <SideRow
          label={t("sentiment.side_corr")}
          value={signed(book.bond_correlation, 2)}
          pill={
            <DriftPill now={book.bond_correlation} then={book.bond_correlation_then} />
          }
        />
      )}
      <SideRow
        label={t("sentiment.usd_share")}
        value={share(book.usd_share)}
        pill={
          drag === null ? undefined : (
            <span className={`sn-pill ${drag >= 0 ? "sn-pill-up" : "sn-pill-down"}`}>
              {t("sentiment.fx_pill", { value: percent(drag, 2) })}
            </span>
          )
        }
      />
      {/* The dollar share survived the outage — it is read off the positions
          — while the beta and the correlation need the index series. Say so
          under the rows rather than letting two "n/a"s explain themselves. */}
      {book.unavailable && <DownBody reason={book.unavailable} onRetry={onRetry} />}
      <p className="sn-help">{t("sentiment.side_help")}</p>
      <a className="sn-more" href="#ag-book">
        {t("sentiment.side_more")}
      </a>
    </div>
  );
}
