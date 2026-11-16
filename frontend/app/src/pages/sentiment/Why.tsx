/**
 * Thirty seconds: the composite's eight inputs, each with its own level.
 *
 * The whole argument for building our own index instead of showing someone
 * else's is here — the number explains itself. An input that could not be
 * built keeps its row, dimmed and named, because "we are missing the credit
 * leg today" is information and a silently shorter average is not.
 */

import { useT } from "../../shell/i18n";
import { DownBody } from "./Down";
import { NA } from "./format";
import { fromMiddle } from "./logic";
import type { Pulse } from "./types";

/**
 * The eight inputs in reading order. The API sends the ones it built and names
 * the ones it could not, so the union of the two is the full set; this only
 * decides the order they are read in, and anything unexpected still gets a row.
 */
const ORDER = [
  "momentum",
  "breadth",
  "volatility",
  "term",
  "credit",
  "haven",
  "junk",
  "global_risk",
];

/**
 * How few inputs the composite will still quote a score on. Mirrors
 * `stocks.analysis.sentiment.MIN_COMPONENTS`, which the API does not send: it
 * is part of the sentence that says what the number is missing.
 */
const FLOOR = 4;

export function Why({ pulse, onRetry }: { pulse: Pulse; onRetry?: () => void }) {
  const t = useT();
  const head = (
    <div className="sn-sec-head">
      <h2 className="sn-sec-t" id="ag-why">
        {t("sentiment.why_title")}
      </h2>
      <span className="sn-spacer" />
      <span className="sn-mono sn-comp-key">
        <span>
          <i className="sn-key-te" />
          {t("sentiment.why_key_stress")}
        </span>
        <span>
          <i className="sn-key-ap" />
          {t("sentiment.why_key_appetite")}
        </span>
        <span>
          <i className="sn-key-mk" />
          {t("sentiment.why_key_month")}
        </span>
      </span>
    </div>
  );
  // Nothing was built, so there are no rows to dim: eight "n/a" bars would
  // read as eight inputs that each failed, when one feed did.
  if (pulse.unavailable) {
    return (
      <>
        {head}
        <DownBody reason={pulse.unavailable} onRetry={onRetry} />
      </>
    );
  }
  const built = new Map(pulse.components.map((c) => [c.key, c]));
  const extras = [...built.keys(), ...pulse.missing].filter(
    (key) => !ORDER.includes(key),
  );
  const keys = [...ORDER.filter((k) => built.has(k) || pulse.missing.includes(k))];
  // A key the server knows and this list does not still gets a row: the
  // registry lives in Python and a page that silently drops what it does not
  // recognise is a page that averages fewer things than it says it does.
  keys.push(...extras);
  const total = pulse.components.length + pulse.missing.length;

  return (
    <>
      {head}

      <div className="sn-comp">
        {keys.map((key) => {
          const comp = built.get(key);
          const score = comp?.score ?? null;
          const then = comp?.then ?? null;
          return (
            <div
              className={score === null ? "sn-comp-row sn-dim" : "sn-comp-row"}
              key={key}
            >
              <span className="sn-comp-l">
                <span>{t(`sentiment.comp_${key}`)}</span>
                <span className="sn-comp-sub">{t(`sentiment.comp_${key}_sub`)}</span>
              </span>
              {score === null ? (
                <span className="sn-comp-track sn-comp-empty">
                  <span className="sn-comp-none">{t("sentiment.comp_none")}</span>
                </span>
              ) : (
                <span
                  className="sn-comp-track"
                  role="img"
                  aria-label={
                    then === null
                      ? t("sentiment.comp_aria_plain", {
                          name: t(`sentiment.comp_${key}`),
                          score: Math.round(score),
                        })
                      : t("sentiment.comp_aria", {
                          name: t(`sentiment.comp_${key}`),
                          score: Math.round(score),
                          then: Math.round(then),
                        })
                  }
                >
                  {/* From the 50 line outwards: appetite to the right,
                      tension to the left, so the side says the direction and
                      the length says how far. A bar filled from the left
                      made a 31 and a 69 differ by length alone. */}
                  <span className="sn-comp-axis" />
                  <span
                    className={`sn-comp-fill sn-fill-${fromMiddle(score).side}`}
                    style={{ width: `${fromMiddle(score).width}%` }}
                  />
                  {then !== null && (
                    <span
                      className="sn-comp-mark"
                      style={{
                        left: `calc(${Math.max(0, Math.min(100, then))}% - 1px)`,
                      }}
                    />
                  )}
                </span>
              )}
              {/* The raw reading in its own units — +4.2%, 15.2, 1.19. The bar
                  already encodes the 0-100 score; the number beside it is what
                  the input actually read, formatted server-side by the registry
                  that knows whether it is a percent, a ratio or a spread. */}
              <span className="sn-comp-v">{comp?.text ?? NA}</span>
            </div>
          );
        })}
      </div>

      {/* What the score is missing, said out loud. A composite that quietly
          averages six inputs one day and eight the next is a different number
          wearing the same name. */}
      <div className={`sn-strip ${pulse.missing.length ? "sn-strip-warn" : ""}`}>
        <span>
          {pulse.missing.length
            ? t("sentiment.pulse_missing", {
                names: pulse.missing.map((k) => t(`sentiment.comp_${k}`)).join(", "),
                live: pulse.components.length,
                total,
                floor: FLOOR,
              })
            : t("sentiment.pulse_complete", { total })}
        </span>
      </div>
    </>
  );
}
