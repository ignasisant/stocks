/**
 * Whether a ticker the model gave is the security the reader traded.
 *
 * The model names each holding of a statement no parser knows, and a name it
 * half remembers comes back as a real ticker all the same: listed, priced,
 * and somebody else's company. The server holds each name to its prices and
 * doubts the ones whose fills sit far from their closes (`Preview.doubted`):
 * those are asked about here (`Doubted`), and any other ticker of such a
 * reading can be called wrong unasked (`Wrong`).
 *
 * Either way the reader confirms the ticker or names the company it really
 * was and picks its line — the venue picker's search (`Lines`): each line
 * priced on the day of the latest fill, only one that closed near the fills
 * usable. The server checks the line again and records the answer; nothing is
 * written until the commit, which sends the rows as corrected (`fixes.ts`).
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { answerTicker } from "./api";
import type { Row, TickerWhy } from "./api";
import { inDoubt } from "./fixes";
import type { Fix } from "./fixes";
import { Glyph } from "./Glyph";
import { tradedAs } from "./lines";
import type { Traded } from "./lines";
import { useVocabulary } from "./text";
import { Lines } from "./Venues";

type Answer = (fix: Fix) => void;

export function Doubted({
  codes,
  rows,
  onAnswer,
}: {
  codes: string[];
  /** The rows as they stand, the reader's earlier answers applied. */
  rows: Row[];
  onAnswer: Answer;
}) {
  const vocab = useVocabulary();
  // The doubt is on a ticker in one currency: its fills are the doubted rows'.
  const doubtful = rows.filter(inDoubt);
  return (
    <div className="im-venues">
      <p className="im-fine">
        {vocab.tn("import.doubted_note", codes.length, { tickers: codes.join(", ") })}
      </p>
      {codes.map((code) => {
        const traded = tradedAs(doubtful, code);
        return traded ? (
          <Ask code={code} key={code} onAnswer={onAnswer} traded={traded} why="doubt" />
        ) : null;
      })}
    </div>
  );
}

/**
 * Every other ticker the model gave, behind a fold: a wrong name whose price
 * happened to sit near the right one's is not doubted, and the reader who
 * sees it needs a way to say so.
 */
export function Wrong({
  rows,
  asked,
  onAnswer,
}: {
  rows: Row[];
  /** Tickers asked about elsewhere on the page: doubted, or unpriced. */
  asked: string[];
  onAnswer: Answer;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const codes = [...new Set(rows.map((row) => row.ticker))]
    .filter((code) => !asked.includes(code))
    .sort();
  const named = codes.flatMap((code) => {
    const traded = tradedAs(rows, code);
    return traded ? [{ code, traded }] : [];
  });
  if (named.length === 0) return null;
  return (
    <details
      className="im-skipped"
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <Glyph name="down" />
        <span className="im-h3">{t("import.wrong_title")}</span>
        <span className="im-fine">{t("import.wrong_note")}</span>
      </summary>
      {/* Mounted when opened: a row per ticker of the statement. */}
      {open && (
        <div className="im-skipped-body im-venues">
          {named.map(({ code, traded }) => (
            <Ask
              code={code}
              key={code}
              onAnswer={onAnswer}
              traded={traded}
              why="reader"
            />
          ))}
        </div>
      )}
    </details>
  );
}

function Ask({
  code,
  traded,
  why,
  onAnswer,
}: {
  code: string;
  traded: Traded;
  why: TickerWhy;
  onAnswer: Answer;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { currency, fills } = traded;

  const right = () => {
    onAnswer({ code, currency, symbol: code });
    // Sent for the count of doubts that were wrong themselves; the reader's
    // answer stands on this page whether or not it arrives.
    void answerTicker(code, currency, fills, "", why).catch(() => undefined);
  };

  return (
    <div className="im-venue">
      <div className="im-venue-head im-ask-head">
        {/* With its name: the name is how a reader tells it is the wrong one. */}
        <TickerCell className="im-tick" ticker={code} />
        {why === "doubt" && <span className="im-fine">{t("import.ticker_ask")}</span>}
        {open ? (
          <button
            className="im-btn im-btn-text"
            onClick={() => setOpen(false)}
            type="button"
          >
            {t("common.cancel")}
          </button>
        ) : (
          <button
            className="im-btn im-btn-outline im-btn-sm"
            onClick={() => setOpen(true)}
            type="button"
          >
            {t("import.ticker_change")}
          </button>
        )}
        {why === "doubt" && (
          <button className="im-btn im-btn-text" onClick={right} type="button">
            {t("import.ticker_right")}
          </button>
        )}
      </div>

      {open && (
        <Lines
          code={code}
          first={null}
          label={t("import.ticker_query", { code })}
          onUse={async (symbol) => {
            await answerTicker(code, currency, fills, symbol, why);
            onAnswer({ code, currency, symbol });
          }}
          refusal={(symbol) => t("import.ticker_refused", { symbol })}
          skip={code}
          traded={traded}
          working={(symbol) => t("import.work_ticker", { symbol })}
        />
      )}
    </div>
  );
}
