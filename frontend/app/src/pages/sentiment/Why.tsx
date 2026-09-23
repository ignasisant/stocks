/**
 * Thirty seconds: the composite's eight inputs, each with its own level.
 *
 * The whole argument for building our own index instead of showing someone
 * else's is here — the number explains itself. An input that could not be
 * built keeps its row, dimmed and named, because "we are missing the credit
 * leg today" is information and a silently shorter average is not.
 */

import { useT } from "../../shell/i18n";
import { NA, fixed } from "./format";
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

/** Red at the fear end, green at the appetite end, neutral through the middle. */
function scoreClass(score: number): string {
  if (score < 40) return "sn-fill-bad";
  if (score < 60) return "sn-fill-flat";
  return "sn-fill-good";
}

export function Why({ pulse }: { pulse: Pulse }) {
  const t = useT();
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
      <div className="sn-sec-head">
        <h3 className="sn-sec-t" id="ag-why">
          {t("sentiment.why_title")}
        </h3>
        <span className="sn-mono">{t("sentiment.why_hint")}</span>
      </div>

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
                <span className="sn-comp-track">
                  <span
                    className={`sn-comp-fill ${scoreClass(score)}`}
                    style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
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
              {/* The score, not the raw reading: the levels behind these eight
                  are a percentage, a ratio and a spread, and the API sends no
                  format for them — a number printed in the wrong unit is worse
                  than the one the bar already encodes. */}
              <span className="sn-comp-v">{score === null ? NA : fixed(score, 0)}</span>
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
