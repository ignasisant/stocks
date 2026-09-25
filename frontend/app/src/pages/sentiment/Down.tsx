/**
 * What a block says when its source died — one component for every block.
 *
 * The page's promise is that every block degrades on its own and keeps its
 * heading, so the heading stays with the block that owns it and only the body
 * lives here: the title of the failure, the reason in the reader's own terms,
 * a way back, and "last attempt hh:mm · source …" — the line `sentiment.py`'s
 * `_source_down` prints, and the one that tells a reader whether it is worth
 * waiting (a Yahoo throttle clears in a minute; a FRED outage does not).
 *
 * The reason comes from the server in two shapes: an `unavailable` key on a
 * payload that still answered 200, or an `ApiError` whose `reason` the API's
 * exception handlers set. `reasonOf` folds the second into the first so no
 * block has to know which one it got.
 */

import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";

/** Who to name when a price block cannot be drawn. Not translated: a name. */
export const YAHOO = "Yahoo Finance";

/** The reason keys the copy below distinguishes; anything else is `no_data`. */
const REASONS = new Set(["rate_limited", "offline", "no_data"]);

/**
 * A failed fetch, as the same key an `unavailable` field carries.
 *
 * A `TypeError` out of `fetch` is the browser failing to reach anybody, which
 * is "offline" from where the reader sits. The API's own throttle on this
 * client (`throttled`) is not Yahoo's, so it gets the generic family copy
 * rather than a sentence blaming the provider.
 */
export function reasonOf(error: unknown): string {
  if (error instanceof ApiError && REASONS.has(error.reason ?? "")) {
    return error.reason as string;
  }
  if (error instanceof TypeError) return "offline";
  return "no_data";
}

/** hh:mm, as the Streamlit stamp prints it — seconds would be false precision. */
function clock(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function DownBody({
  reason,
  family = "prices",
  origin = YAHOO,
  onRetry,
}: {
  reason: string;
  /** Which "source is down" copy fits: a price feed or a macro publisher. */
  family?: "prices" | "macro";
  /** The source named in the stamp. */
  origin?: string;
  /** Omitted where the retry would refetch a query that did not fail. */
  onRetry?: () => void;
}) {
  const t = useT();
  const base =
    family === "prices"
      ? "sentiment.prices_unavailable"
      : "sentiment.macro_unavailable";
  // The reason the API gave, in the reader's own terms; `no_data` has no copy
  // of its own, so it falls back to the block's own family message.
  const body =
    reason === "rate_limited"
      ? "common.rate_limited"
      : reason === "offline"
        ? "common.offline"
        : base;
  return (
    <>
      <div className="sn-down">
        <span className="sn-down-t">{t(`${base}_title`)}</span>
        <span className="sn-down-b">{t(body)}</span>
      </div>
      {onRetry && (
        <button className="sn-btn" onClick={onRetry}>
          {t("sentiment.down_retry")}
        </button>
      )}
      <p className="sn-caption">
        {t("sentiment.down_stamp", { time: clock(), source: origin })}
      </p>
    </>
  );
}
