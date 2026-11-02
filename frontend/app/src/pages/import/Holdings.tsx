/**
 * A holdings report, dated line by line before anything is written.
 *
 * The file says what is held and at best the average paid, never when. Each
 * line asks for the price paid (the report's own cost, when it printed one)
 * and offers the days that price was on the board: the stretches of sessions
 * whose low-high range held it (`/import/buy-dates`), newest first. The reader
 * picks one or types a day; a line left undated is left out, never guessed.
 *
 * The days are asked per line, on a press: each answer is a download of the
 * listing's whole history, and a report of thirty lines should not spend thirty
 * of them on arrival. The commit (`children`) is the same panel as a
 * statement's, handed the dated lines as its rows.
 */

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { Status } from "../../ui/Status";
import { buyDates } from "./api";
import type { BuyDates, Holding, Preview } from "./api";
import { Eyebrow } from "./Card";
import {
  MIN_DAY,
  boughtAs,
  currencyProblem,
  dayProblem,
  priceOf,
  priceProblem,
  today,
  undated,
} from "./dating";
import type { Dating, Problem } from "./dating";
import { useVocabulary } from "./text";

export function Holdings({
  preview,
  children,
}: {
  preview: Preview;
  /** The commit, handed the preview with the dated lines as its rows. */
  children?: (dated: Preview) => ReactNode;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const holdings = useMemo(() => preview.holdings ?? [], [preview.holdings]);
  const [dating, setDating] = useState<Record<number, Dating>>(() =>
    Object.fromEntries(holdings.map((holding) => [holding.row, undated(holding)])),
  );

  const of = (holding: Holding) => dating[holding.row] ?? undated(holding);
  const rows = holdings.flatMap((holding) => {
    const row = boughtAs(holding, of(holding));
    return row ? [row] : [];
  });
  const dated = { ...preview, importable: rows, rejected: [], skipped: [] };

  const change = (holding: Holding, patch: Partial<Dating>) =>
    setDating((prior) => ({
      ...prior,
      [holding.row]: { ...(prior[holding.row] ?? undated(holding)), ...patch },
    }));

  return (
    <section aria-labelledby="im-hold-title" className="im-card im-review">
      <header className="im-review-head">
        <h2 className="im-review-title" id="im-hold-title">
          <Eyebrow n={3}>{t("import.hold_title")}</Eyebrow>
          <span className="im-review-sum">
            {vocab.tn("import.hold_sum", rows.length, {
              total: vocab.num(holdings.length, 0),
            })}
          </span>
        </h2>
        <p className="im-fine">{t("import.hold_note")}</p>
      </header>

      {children?.(dated)}

      <ul className="im-holds">
        {holdings.map((holding) => (
          <HoldingLine
            dating={of(holding)}
            holding={holding}
            key={holding.row}
            onChange={(patch) => change(holding, patch)}
          />
        ))}
      </ul>
    </section>
  );
}

type Asked =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "failed"; busy: boolean }
  | { state: "loaded"; answer: BuyDates; price: number };

function HoldingLine({
  holding,
  dating,
  onChange,
}: {
  holding: Holding;
  dating: Dating;
  onChange: (patch: Partial<Dating>) => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [asked, setAsked] = useState<Asked>({ state: "idle" });
  const price = priceOf(dating.price);
  const id = `im-hold-${holding.row}`;
  const now = today();
  const wrong = {
    price: priceProblem(dating.price),
    currency: currencyProblem(dating.currency),
    date: dayProblem(dating.date, now),
  };

  const ask = async () => {
    if (price === null) return;
    setAsked({ state: "loading" });
    try {
      const answer = await buyDates(holding, price);
      setAsked({ state: "loaded", answer, price });
      // The bars' line is what prices the buy; their currency is the price's
      // when the report never said.
      onChange({
        symbol: answer.symbol,
        currency: dating.currency || answer.currency,
      });
    } catch (error) {
      setAsked({
        state: "failed",
        busy: error instanceof ApiError && error.status === 503,
      });
    }
  };

  const answer = asked.state === "loaded" ? asked.answer : null;

  return (
    <li className="im-hold">
      <div className="im-hold-head">
        <TickerCell className="im-tick" ticker={dating.symbol || holding.ticker} />
        <span className="im-fine">
          {vocab.tn("import.hold_shares", holding.quantity, {
            qty: vocab.num(holding.quantity, holding.quantity % 1 ? 4 : 0),
          })}
        </span>
      </div>

      <div className="im-hold-fields">
        <label className="im-hold-field">
          <span className="im-fine">{t("import.hold_price")}</span>
          <span className="im-hold-money">
            <input
              aria-describedby={`${id}-money-error ${id}-days`}
              aria-invalid={wrong.price !== null}
              autoComplete="off"
              className="im-input im-hold-price"
              inputMode="decimal"
              onChange={(event) => {
                onChange({ price: event.target.value });
                setAsked({ state: "idle" });
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void ask();
              }}
              value={dating.price}
            />
            <input
              aria-describedby={`${id}-money-error`}
              aria-invalid={wrong.currency !== null}
              aria-label={t("import.hold_currency")}
              autoCapitalize="characters"
              autoComplete="off"
              className="im-input im-hold-ccy"
              maxLength={3}
              onChange={(event) =>
                onChange({ currency: event.target.value.toUpperCase() })
              }
              placeholder="EUR"
              spellCheck={false}
              value={dating.currency}
            />
          </span>
          <FieldError id={`${id}-money-error`} problem={wrong.price ?? wrong.currency} />
        </label>
        <button
          className="im-btn im-btn-outline"
          disabled={price === null || wrong.currency !== null || asked.state === "loading"}
          onClick={() => void ask()}
          type="button"
        >
          {t("import.hold_find")}
        </button>
        <label className="im-hold-field">
          <span className="im-fine">{t("import.hold_date")}</span>
          <input
            aria-describedby={`${id}-date-error`}
            aria-invalid={wrong.date !== null}
            className="im-input im-hold-date"
            max={now}
            min={MIN_DAY}
            onChange={(event) => onChange({ date: event.target.value })}
            type="date"
            value={dating.date}
          />
          <FieldError id={`${id}-date-error`} problem={wrong.date} />
        </label>
      </div>

      <div aria-live="polite" className="im-hold-days" id={`${id}-days`}>
        {asked.state === "loading" && <Status label={t("import.hold_finding")} />}
        {asked.state === "failed" && (
          <p className="im-bad">
            {t(asked.busy ? "import.venue_retry" : "common.failed")}
          </p>
        )}
        {answer && asked.state === "loaded" && answer.runs.length === 0 && (
          <p className="im-fine">
            {t("import.hold_none", {
              price: vocab.num(asked.price, 2),
              currency: answer.currency,
              first: answer.first,
            })}
          </p>
        )}
        {answer && asked.state === "loaded" && answer.runs.length > 0 && (
          <>
            <p className="im-fine">
              {t("import.hold_days", {
                price: vocab.num(asked.price, 2),
                currency: answer.currency,
              })}
            </p>
            <div className="im-chips">
              {answer.runs.map((run) => (
                <button
                  aria-pressed={dating.date === run.day}
                  className={`im-chip${dating.date === run.day ? " im-chip-on" : ""}`}
                  key={run.start}
                  onClick={() => onChange({ date: run.day })}
                  title={
                    run.sessions > 1
                      ? t("import.hold_run", {
                          start: run.start,
                          end: run.end,
                          n: vocab.num(run.sessions, 0),
                        })
                      : undefined
                  }
                  type="button"
                >
                  <span className="im-mono">{run.day}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </li>
  );
}

function FieldError({ id, problem }: { id: string; problem: Problem | null }) {
  const t = useT();
  return (
    <span aria-live="polite" className="im-hold-error" id={id}>
      {problem ? t(problem, { min: MIN_DAY }) : null}
    </span>
  );
}
