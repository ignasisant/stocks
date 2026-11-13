/**
 * The read, at the top of a company's page: one line per question a reader
 * brings to it — is the business any good, is the price, which way is it
 * going, what do the analysts and the insiders say, and when is the next
 * report — each coloured by the card that answers it in full and a link to
 * that card. Under them, the Review page's verdict on it as a buy.
 *
 * No judgement is made here. Every tone is the one its own card already
 * draws: the moat's band, the P/E against its five years and the trend
 * (`Price.tsx` `cell`), the street's mean rating (`Analysts.tsx`). A line
 * whose card has not answered yet says so rather than guessing.
 */

import { DASH, isNum, percent } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { ratingLabel, ratingTone } from "./Analysts";
import { cell, isoToday } from "./Price";
import { jumpTo, sectionId, type SectionKey } from "./SectionTabs";
import { Judged } from "./Sections";
import { Card } from "./ui";
import type {
  Analysts,
  EarningsEvent,
  Insiders,
  Metrics,
  Moat,
  Quote,
  Trend,
  Valuation,
} from "./types";

/** undefined: not answered yet; null: the feed has nothing. */
type Maybe<T> = T | null | undefined;

type Signal = {
  key: string;
  label: string;
  text: string;
  /** up | down | warn | flat — the `ag-tone-*` ink of the dot. */
  tone: string;
  to: SectionKey;
};

/** The cards' own tone words, on the app's four inks. */
function ink(tone: string | null | undefined): string {
  if (tone === "green" || tone === "up") return "up";
  if (tone === "red" || tone === "down") return "down";
  if (tone === "orange" || tone === "warn") return "warn";
  return "flat";
}

export function ReadingSection({
  trend,
  valuation,
  events,
  quote,
  metrics,
  analysts,
  insiders,
  moat,
}: {
  trend: Trend | null;
  valuation: Valuation | null;
  events: EarningsEvent[];
  quote: Quote | null;
  metrics: Maybe<Metrics>;
  analysts: Maybe<Analysts>;
  insiders: Maybe<Insiders>;
  moat: Maybe<Moat>;
}) {
  const t = useT();
  const pending = t("ticker.read_pending");
  const shared = {
    bars: null,
    live: quote?.price ?? trend?.price ?? null,
    fund: null,
    stats: null,
    quote,
    valuation,
    trend,
    events,
    today: isoToday(),
    t,
  };
  const joined = (...parts: string[]) =>
    parts.filter((part) => part && part !== DASH).join(" · ") || DASH;

  const pe = cell("pe", shared);
  const run = cell("trend", shared);
  const next = cell("next_results", shared);

  const signals: Signal[] = [
    {
      key: "business",
      label: t("ticker.read_business"),
      text:
        moat === undefined
          ? pending
          : moat?.rating_key
            ? t("ticker.read_moat", { rating: t(moat.rating_key) })
            : DASH,
      tone: ink(moat?.rating_tone),
      to: "business",
    },
    {
      key: "price",
      label: t("ticker.read_price"),
      text: pe.value === DASH ? DASH : joined(`${pe.label} ${pe.value}`, pe.note),
      tone: ink(pe.tone),
      to: "valuation",
    },
    {
      key: "trend",
      label: t("ticker.trend"),
      text: joined(run.value, run.note),
      tone: ink(run.tone),
      to: "price",
    },
    {
      key: "analysts",
      label: t("ticker.read_analysts"),
      text:
        analysts === undefined
          ? pending
          : !analysts?.covered
            ? t("ticker.read_uncovered")
            : joined(
                ratingLabel(t, analysts.rating),
                isNum(analysts.targets?.upside_median)
                  ? t("ticker.read_target", {
                      pct:
                        percent(analysts.targets.upside_median, {
                          digits: 0,
                          signed: "always",
                          tight: true,
                        }) ?? DASH,
                    })
                  : "",
              ),
      tone:
        analysts?.covered && isNum(analysts.rating_mean)
          ? ratingTone(analysts.rating_mean)
          : "flat",
      to: "opinions",
    },
    {
      key: "insiders",
      label: t("ticker.read_insiders"),
      text: insiderText(t, insiders, pending),
      // Only a cluster of buyers reads as a signal: insiders sell for a
      // hundred reasons (taxes, a house, a vesting schedule) and buy for one.
      tone: insiders?.summary?.cluster_buy ? "up" : "flat",
      to: "opinions",
    },
    {
      key: "calendar",
      label: next.label,
      text: joined(next.value, next.note),
      tone: "flat",
      to: "price",
    },
  ];

  const judged = metrics?.judged;
  return (
    <Card title={t("ticker.reading")}>
      <ul className="tk-signals">
        {signals.map((one) => (
          <li key={one.key}>
            <a
              className="tk-signal"
              href={`#${sectionId(one.to)}`}
              onClick={(event) => {
                event.preventDefault();
                jumpTo(one.to);
              }}
            >
              <span
                className={`tk-signal-dot ag-tone-${one.tone}`}
                aria-hidden="true"
              />
              <span className="tk-signal-text">
                <b>{one.label}</b>
                <span>{one.text}</span>
              </span>
            </a>
          </li>
        ))}
      </ul>
      {metrics && judged && judged.verdict !== "unrated" ? (
        <Judged ticker={metrics.ticker} judged={judged} cautions={metrics.cautions} />
      ) : null}
    </Card>
  );
}

function insiderText(
  t: ReturnType<typeof useT>,
  insiders: Maybe<Insiders>,
  pending: string,
): string {
  if (insiders === undefined) return pending;
  const summary = insiders?.summary;
  if (!insiders?.source || !summary) return t("ticker.read_insiders_none");
  if (summary.cluster_buy)
    return t("ticker.read_insiders_cluster", { n: summary.buyers });
  if (summary.buy_count === 0 && summary.sell_count === 0) {
    return t("ticker.read_insiders_quiet");
  }
  return summary.net_value > 0
    ? t("ticker.read_insiders_buying")
    : t("ticker.read_insiders_selling");
}
