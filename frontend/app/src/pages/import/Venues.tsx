/**
 * The codes the search could not place, and the reader's way to place them.
 *
 * Such a code imports unpriced: held at cost, no market value, no return. The
 * reader usually knows what it is, though, so each one offers its lines —
 * found by the security's name on the venues of the code's currency, each
 * priced on the day of the code's latest fill — and only a line that closed
 * near the fills can be picked (`POST /import/venue` checks again). The pick
 * is the code's answer for every later price, so the preview is asked again
 * (`onPicked`) and the warning goes with it.
 *
 * Folded until asked: each opening is a search and a price download per line,
 * and a statement with five such codes should not spend them on arrival.
 * "Leave unpriced" only folds the row away: the rows import either way.
 *
 * The search itself (`Lines`) is shared with the question of whether a ticker
 * is the right company (`Tickers.tsx`), which offers the same priced lines.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Status } from "../../ui/Status";
import { pickVenue, venueOptions } from "./api";
import type { Row } from "./api";
import { useVocabulary } from "./text";
import { ranked, tradedAs, verdict } from "./lines";
import type { Traded } from "./lines";

export function Unlisted({
  codes,
  rows,
  onPicked,
}: {
  codes: string[];
  /** The preview's importable rows, whose fills a line is checked against. */
  rows: Row[];
  onPicked: () => void;
}) {
  const vocab = useVocabulary();
  return (
    <div className="im-venues">
      <p className="im-fine">
        {vocab.tn("import.unlisted_note", codes.length, { tickers: codes.join(", ") })}
      </p>
      {codes.map((code) => {
        const traded = tradedAs(rows, code);
        return traded ? (
          <Venue code={code} key={code} onPicked={onPicked} traded={traded} />
        ) : null;
      })}
    </div>
  );
}

function Venue({
  code,
  traded,
  onPicked,
}: {
  code: string;
  traded: Traded;
  onPicked: () => void;
}) {
  const t = useT();
  const [left, setLeft] = useState(false);
  const [open, setOpen] = useState(false);

  return (
    <div className="im-venue">
      <div className="im-venue-head">
        <TickerCell className="im-tick" name={false} ticker={code} />
        {left ? (
          <>
            <span className="im-fine">{t("import.venue_left")}</span>
            <button
              className="im-btn im-btn-text"
              onClick={() => setLeft(false)}
              type="button"
            >
              {t("import.venue_undo")}
            </button>
          </>
        ) : (
          <>
            <span className="im-fine">
              {t("import.venue_none", { currency: traded.currency })}
            </span>
            {!open && (
              <button
                className="im-btn im-btn-outline im-btn-sm"
                onClick={() => setOpen(true)}
                type="button"
              >
                {t("import.venue_choose")}
              </button>
            )}
            <button
              className="im-btn im-btn-text"
              onClick={() => {
                setLeft(true);
                setOpen(false);
              }}
              type="button"
            >
              {t("import.venue_leave")}
            </button>
          </>
        )}
      </div>

      {!left && open && (
        <Lines
          code={code}
          first=""
          label={t("import.venue_query", { code })}
          onUse={async (symbol) => {
            await pickVenue(code, traded.currency, traded.fills, symbol);
            onPicked();
          }}
          refusal={(symbol) => t("import.venue_refused", { symbol })}
          traded={traded}
          working={(symbol) => t("import.work_venue", { symbol })}
        />
      )}
    </div>
  );
}

/**
 * The lines a search finds on the venues of the fills' currency, each priced
 * on the day of the latest fill, and the one the reader uses. Only a line
 * that closed near the fills can be used, and `onUse` asks the server, which
 * checks it again: a 409 is said in `refusal`'s words, a 503 as Yahoo's.
 */
export function Lines({
  code,
  traded,
  first,
  skip,
  label,
  working,
  refusal,
  onUse,
}: {
  code: string;
  traded: Traded;
  /** What is searched on opening (empty is the code itself); null waits for
   *  the reader's own words. */
  first: string | null;
  /** A line not to offer: the ticker the rows already carry. */
  skip?: string;
  /** The search field's name. */
  label: string;
  /** What is said while `onUse` runs, and when the server refuses the line. */
  working: (symbol: string) => string;
  refusal: (symbol: string) => string;
  onUse: (symbol: string) => Promise<void>;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [query, setQuery] = useState("");
  // null has searched nothing yet; each search is a new ask, even of the
  // same words.
  const [ask, setAsk] = useState<{ query: string; n: number } | null>(
    first === null ? null : { query: first, n: 1 },
  );
  const [picking, setPicking] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const found = useApi(
    async () =>
      ask ? await venueOptions(code, traded.currency, traded.fills, ask.query) : null,
    [ask],
  );

  const search = (event: FormEvent) => {
    event.preventDefault();
    setRefused(null);
    setAsk((prior) => ({ query: query.trim(), n: (prior?.n ?? 0) + 1 }));
  };

  const use = async (symbol: string) => {
    setPicking(symbol);
    setRefused(null);
    try {
      await onUse(symbol);
    } catch (error) {
      setRefused(
        error instanceof ApiError && error.status === 409
          ? refusal(symbol)
          : error instanceof ApiError && error.status === 503
            ? t("import.venue_retry")
            : t("common.failed"),
      );
    } finally {
      setPicking(null);
    }
  };

  const options = found.state === "loaded" && found.data ? found.data : null;
  const lines = options
    ? ranked(options.options).filter((option) => option.symbol !== skip)
    : [];

  return (
    <div className="im-venue-body">
      <form className="im-venue-search" onSubmit={search} role="search">
        <input
          aria-label={label}
          autoCapitalize="off"
          autoComplete="off"
          autoCorrect="off"
          className="im-input"
          enterKeyHint="search"
          spellCheck={false}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("import.venue_query_hint")}
          type="search"
          value={query}
        />
        <button
          className="im-btn im-btn-outline"
          disabled={found.state === "loading"}
          type="submit"
        >
          {t("import.venue_search")}
        </button>
      </form>

      {found.state === "loading" && <Status label={t("import.work_venues")} />}
      {found.state === "failed" && <p className="im-bad">{t("common.failed")}</p>}

      {ask && options && lines.length === 0 && (
        <p className="im-fine">
          {t("import.venue_nothing", {
            query: ask.query || code,
            currency: options.currency,
          })}
        </p>
      )}

      {options && lines.length > 0 && (
        <>
          <p className="im-fine">
            {t("import.venue_against", {
              price: vocab.num(options.price, 2),
              day: options.day,
            })}
          </p>
          <ul className="im-venue-list">
            {lines.map((option) => {
              const said = verdict(option);
              return (
                <li className={`im-venue-opt im-venue-${said}`} key={option.symbol}>
                  <TickerCell className="im-tick" name={false} ticker={option.symbol} />
                  <span className="im-venue-name" title={option.name}>
                    {option.name}
                    {option.exchange && (
                      <span className="im-faint"> · {option.exchange}</span>
                    )}
                  </span>
                  <span className="im-venue-close">
                    {option.close === null ? "—" : vocab.num(option.close, 2)}
                  </span>
                  <span className="im-venue-tag">{t(`import.venue_${said}`)}</span>
                  <button
                    className="im-btn im-btn-outline im-btn-sm"
                    disabled={said !== "agrees" || picking !== null}
                    onClick={() => void use(option.symbol)}
                    type="button"
                  >
                    {t("import.venue_use")}
                  </button>
                </li>
              );
            })}
          </ul>
          {options.throttled && (
            <p className="im-fine">{t("import.venue_throttled")}</p>
          )}
        </>
      )}

      {picking && <Status label={working(picking)} />}
      {refused && <p className="im-bad">{refused}</p>}
    </div>
  );
}
