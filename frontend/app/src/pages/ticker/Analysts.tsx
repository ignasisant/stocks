/**
 * What the sell side says about a share: its verdict and how that has moved,
 * where it puts the price in a year, and which way it is revising earnings.
 *
 * Every figure here is consensus — an aggregate of opinions with the sell
 * side's incentives — and the card says so in its caption rather than letting
 * a target sit beside the filed figures as if it were one. Three readings
 * matter more than the headline verdict, and each gets its own block:
 *
 * - the median target beside the mean, because one outlier drags a mean;
 * - how far apart the targets are, because a mean of wild disagreement is a
 *   number nobody actually forecast;
 * - the revisions, because the direction analysts are moving EPS has said
 *   more about the next quarters than the label they print on it.
 */

import { useLang, useT } from "../../shell/i18n";
import { Kpi, KpiGrid, toneOf, type Tone } from "../../ui/Kpi";
import {
  DASH,
  currencySymbol,
  known,
  money,
  percent,
  signedPercent,
  type Translate,
} from "./format";
import { Banner, Card, Note, Scroll, Subhead, useMobile } from "./ui";
import type { AnalystMonth, Analysts, EpsRevisionRow } from "./types";

/** The five buckets, strongest buy first — the order every bar is drawn in. */
const BUCKETS = ["strong_buy", "buy", "hold", "sell", "strong_sell"] as const;
type Bucket = (typeof BUCKETS)[number];

// A range wider than the mean target itself: the mean is an average of
// disagreements, not a view anybody holds.
const WIDE_DISPERSION = 1;
// A 30-day EPS move this size, both fiscal years the same way, is a trend.
const REVISION_MOVE = 0.01;
// A segment narrower than this share has no room for its count; the title and
// the bar's aria-label still carry it.
const LABELLED_SHARE = 0.1;

export function AnalystsSection({ data }: { data: Analysts }) {
  const t = useT();
  const title = t("ticker.analysts");

  // Nobody publishes on the name, or too few do for a split to mean anything.
  // Said in words: a card that vanishes reads as one that failed to load, and
  // one analyst drawn as a 100% "buy" bar reads as a unanimous street.
  if (data.analysts === 0 && !data.targets) {
    return (
      <Card title={title}>
        <Note>{t("ticker.analysts_none")}</Note>
      </Card>
    );
  }
  if (!data.covered) {
    return (
      <Card title={title}>
        <Note>
          {t("ticker.analysts_thin", { n: data.analysts, min: data.min_coverage })}
        </Note>
      </Card>
    );
  }

  const targets = data.targets;
  const price = (value: number | null) => targetMoney(value, data.currency);
  const raising = trend(data.revisions, 1);
  const cutting = trend(data.revisions, -1);

  return (
    <Card title={title} note={t("ticker.analysts_caption")}>
      <KpiGrid>
        <Kpi
          label={t("ticker.analysts_rating")}
          help={t("ticker.analysts_rating_help")}
          value={ratingLabel(t, data.rating)}
          chip={
            known(data.rating_mean)
              ? {
                  text: `${data.rating_mean.toFixed(1)} / 5`,
                  tone: ratingTone(data.rating_mean),
                }
              : null
          }
        />
        <Kpi label={t("ticker.analysts_count")} value={String(data.analysts)} />
        {targets ? (
          <>
            <Kpi
              label={t("ticker.analysts_target_median")}
              help={t("ticker.analysts_target_median_help")}
              value={price(targets.median)}
              chip={upsideChip(targets.upside_median)}
            />
            <Kpi
              label={t("ticker.analysts_target_mean")}
              value={price(targets.mean)}
              chip={upsideChip(targets.upside_mean)}
            />
            <Kpi
              label={t("ticker.analysts_dispersion")}
              help={t("ticker.analysts_dispersion_help")}
              value={percent(targets.dispersion, 0)}
            />
          </>
        ) : null}
      </KpiGrid>

      {targets && known(targets.dispersion) && targets.dispersion >= WIDE_DISPERSION ? (
        <Banner tone="warn">{t("ticker.analysts_wide")}</Banner>
      ) : null}
      {raising ? <Banner tone="good">{t("ticker.analysts_raising")}</Banner> : null}
      {cutting ? <Banner tone="warn">{t("ticker.analysts_cutting")}</Banner> : null}

      {targets ? <TargetRange data={data} /> : null}
      {data.months.length ? <RatingSplit months={data.months} /> : null}
      {data.revisions.length ? (
        <Revisions rows={data.revisions} currency={data.currency} />
      ) : null}
    </Card>
  );
}

// ------------------------------------------------------------- target range

/**
 * Low to high on one track, the median and mean ticked on it and the price
 * marked where it stands — which may be past either end, so the track
 * stretches to hold it rather than clipping the one point the reader owns.
 */
function TargetRange({ data }: { data: Analysts }) {
  const t = useT();
  const targets = data.targets!;
  const { low, high, median, mean } = targets;
  if (!known(low) || !known(high) || high <= low) return null;
  const now = known(data.price) ? data.price : null;
  const from = Math.min(low, now ?? low);
  const to = Math.max(high, now ?? high);
  const at = (value: number) => `${((value - from) / (to - from)) * 100}%`;
  const price = (value: number | null) => targetMoney(value, data.currency);

  return (
    <div className="tk-targets">
      <Subhead>{t("ticker.analysts_targets")}</Subhead>
      <div className="tk-targets-track" aria-hidden="true">
        <div
          className="tk-targets-band"
          style={{ left: at(low), width: `calc(${at(high)} - ${at(low)})` }}
        />
        {known(median) ? (
          <span className="tk-targets-tick" style={{ left: at(median) }} />
        ) : null}
        {known(mean) ? (
          <span
            className="tk-targets-tick tk-targets-tick-mean"
            style={{ left: at(mean) }}
          />
        ) : null}
        {now !== null ? (
          <span className="tk-targets-price" style={{ left: at(now) }} />
        ) : null}
      </div>
      <ul className="tk-legend tk-targets-legend">
        <li>
          {t("ticker.analysts_low")} {price(low)}
        </li>
        <li>
          <span className="tk-targets-key" />
          {t("ticker.analysts_median")} {price(median)}
        </li>
        <li>
          <span className="tk-targets-key tk-targets-key-mean" />
          {t("ticker.analysts_mean")} {price(mean)}
        </li>
        {now !== null ? (
          <li>
            <span className="tk-targets-key tk-targets-key-price" />
            {t("ticker.col_price")} {price(now)}
          </li>
        ) : null}
        <li>
          {t("ticker.analysts_high")} {price(high)}
        </li>
      </ul>
    </div>
  );
}

// ------------------------------------------------------------- rating split

/** One stacked bar per month, newest on top, so a drift reads downwards. */
function RatingSplit({ months }: { months: AnalystMonth[] }) {
  const t = useT();
  const lang = useLang();
  const newest = [...months].reverse();
  return (
    <div className="tk-ratings">
      <Subhead>{t("ticker.analysts_split")}</Subhead>
      <ul className="tk-ratings-rows">
        {newest.map((month) => (
          <li key={month.month} className="tk-ratings-row">
            <span className="tk-ratings-month">{monthLabel(month.month, lang)}</span>
            <span
              className="tk-ratings-bar"
              role="img"
              aria-label={BUCKETS.map((b) => `${bucketLabel(t, b)} ${month[b]}`).join(
                ", ",
              )}
            >
              {BUCKETS.map((bucket) =>
                month[bucket] ? (
                  <span
                    key={bucket}
                    className={`tk-ratings-seg tk-ratings-${bucket}`}
                    style={{ flexGrow: month[bucket] }}
                    title={`${bucketLabel(t, bucket)}: ${month[bucket]}`}
                  >
                    {month[bucket] / month.total >= LABELLED_SHARE
                      ? month[bucket]
                      : null}
                  </span>
                ) : null,
              )}
            </span>
            <span className="tk-ratings-mean">
              {known(month.mean) ? month.mean.toFixed(1) : DASH}
            </span>
          </li>
        ))}
      </ul>
      <ul className="tk-legend">
        {BUCKETS.map((bucket) => (
          <li key={bucket}>
            <span className={`tk-swatch tk-ratings-${bucket}`} />
            {bucketLabel(t, bucket)}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- revisions

function Revisions({
  rows,
  currency,
}: {
  rows: EpsRevisionRow[];
  currency: string | null;
}) {
  const t = useT();
  const mobile = useMobile();
  const eps = (value: number | null) => targetMoney(value, currency);
  const period = (row: EpsRevisionRow) =>
    t(row.period === "+1y" ? "ticker.analysts_next_fy" : "ticker.analysts_current_fy");
  const votes = (up: number | null, down: number | null) =>
    up === null && down === null ? DASH : `↑${up ?? 0} ↓${down ?? 0}`;

  return (
    <div className="tk-revisions">
      <Subhead>{t("ticker.analysts_revisions")}</Subhead>
      {mobile ? (
        <div className="tk-stack">
          {rows.map((row) => (
            <div className="tk-stack-card" key={row.period}>
              <p className="tk-stack-title">{period(row)}</p>
              <Line label={t("ticker.analysts_eps")} value={eps(row.current)} />
              <Line
                label={t("ticker.analysts_7d")}
                value={move(row.change_7d)}
                change={row.change_7d}
              />
              <Line
                label={t("ticker.analysts_30d")}
                value={move(row.change_30d)}
                change={row.change_30d}
              />
              <Line
                label={t("ticker.analysts_90d")}
                value={move(row.change_90d)}
                change={row.change_90d}
              />
              <Line
                label={t("ticker.analysts_votes_30d")}
                value={votes(row.up_30d, row.down_30d)}
              />
            </div>
          ))}
        </div>
      ) : (
        <Scroll>
          <table className="tk-table">
            <thead>
              <tr>
                <th>{t("ticker.analysts_period")}</th>
                <th>{t("ticker.analysts_eps")}</th>
                <th>{t("ticker.analysts_7d")}</th>
                <th>{t("ticker.analysts_30d")}</th>
                <th>{t("ticker.analysts_90d")}</th>
                <th>{t("ticker.analysts_votes_7d")}</th>
                <th>{t("ticker.analysts_votes_30d")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.period}>
                  <td>{period(row)}</td>
                  <td>{eps(row.current)}</td>
                  <td className={toneClass(row.change_7d)}>{move(row.change_7d)}</td>
                  <td className={toneClass(row.change_30d)}>{move(row.change_30d)}</td>
                  <td className={toneClass(row.change_90d)}>{move(row.change_90d)}</td>
                  <td>{votes(row.up_7d, row.down_7d)}</td>
                  <td>{votes(row.up_30d, row.down_30d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      <Note>{t("ticker.analysts_revisions_caption")}</Note>
    </div>
  );
}

/** A label and its figure, coloured by `change`'s sign when one is given. */
function Line({
  label,
  value,
  change,
}: {
  label: string;
  value: string;
  change?: number | null;
}) {
  return (
    <p className="tk-stack-line">
      <span>{label}</span>
      <span className={change === undefined ? undefined : toneClass(change)}>
        {value}
      </span>
    </p>
  );
}

// ------------------------------------------------------------------ helpers

/**
 * A target or an EPS in the quote's money. Pence-quoted London lines keep
 * their unit after the figure: "£" in front of a pence target is off by 100.
 */
function targetMoney(value: number | null, currency: string | null): string {
  if (!known(value)) return DASH;
  if (currency === "GBp" || currency === "GBX") return `${money(value, 2)}p`;
  return `${currencySymbol(currency)}${money(value, 2)}`;
}

function upsideChip(value: number | null) {
  return known(value) ? { text: signedPercent(value, 1), tone: toneOf(value) } : null;
}

/** 1–2.5 is a buy side, 3.5–5 a sell side, the middle a hold. */
function ratingTone(mean: number): Tone {
  if (mean <= 2.5) return "up";
  if (mean >= 3.5) return "down";
  return "flat";
}

function ratingLabel(t: Translate, rating: string | null): string {
  const labels: Record<string, string> = {
    "strong buy": t("ticker.analysts_strong_buy"),
    buy: t("ticker.analysts_buy"),
    hold: t("ticker.analysts_hold"),
    sell: t("ticker.analysts_sell"),
    "strong sell": t("ticker.analysts_strong_sell"),
  };
  return rating ? (labels[rating] ?? rating) : DASH;
}

function bucketLabel(t: Translate, bucket: Bucket): string {
  return ratingLabel(t, bucket.replace("_", " "));
}

function monthLabel(month: string, lang: string): string {
  const [year, number] = month.split("-").map(Number);
  if (!year || !number) return month;
  return new Date(Date.UTC(year, number - 1, 1)).toLocaleDateString(lang, {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  });
}

/** Rounded to the tenth of a point it prints at, so a drift too small to
 *  show reads 0.0% in neutral, not a red "-0.0%". */
function shown(value: number | null): number | null {
  return known(value) ? Math.round(value * 1000) / 1000 || 0 : value;
}

function move(value: number | null): string {
  return signedPercent(shown(value), 1);
}

function toneClass(value: number | null): string | undefined {
  const rounded = shown(value);
  if (!known(rounded) || rounded === 0) return undefined;
  return rounded > 0 ? "tk-is-green" : "tk-is-red";
}

/**
 * Both fiscal years moved the same way by at least REVISION_MOVE in 30 days.
 * One year alone is too often a single analyst's model change.
 */
function trend(rows: EpsRevisionRow[], sign: 1 | -1): boolean {
  if (rows.length < 2) return false;
  return rows.every(
    (row) => known(row.change_30d) && row.change_30d * sign >= REVISION_MOVE,
  );
}
