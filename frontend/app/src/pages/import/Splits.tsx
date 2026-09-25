/**
 * Splits the book never heard about.
 *
 * A statement prints trades and not the 20-for-1 split between them, so a
 * holding bought before one and never sold keeps a pre-split share count and a
 * pre-split cost basis for ever — and reads as a vast loss against a post-split
 * market price. The import-time rescue in `validate.py` only fires when a
 * *sell* comes up short, and a position nobody sold never comes up short, which
 * is why this repair exists at all and why it is reachable without an import.
 *
 * Two things the Streamlit page does that are not presentation:
 *
 * * the scan runs on request, never on load — it is a Yahoo round-trip per
 *   holding, seconds rather than milliseconds;
 * * every proposal is shown with the evidence that found it before anything is
 *   written, and each one can be left out. `POST /import/splits/apply` takes
 *   named splits precisely so a reader who believes one row and not another can
 *   say so, and re-derives the ratio server-side so a client cannot invent one.
 */

import { useState } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { applySplits, scanSplits } from "./api";
import type { SplitGap } from "./api";
import { ratioLabel, splitKey, useSelection } from "./repairs";
import { useVocabulary } from "./text";

/** A figure the scan could not put a number on. Never rendered as a zero. */
const NONE = "—";

export function Splits({
  enabled,
  onApplied,
}: {
  /** False for a book with no real rows: there is nothing to price. */
  enabled: boolean;
  onApplied: () => void;
}) {
  const t = useT();
  // 0 is "not asked yet", and the state the page returns to after writing: the
  // findings were spent, and re-scanning is another round-trip per holding.
  const [asked, setAsked] = useState(0);
  const [applied, setApplied] = useState(0);
  const scan = useApi(async () => (asked === 0 ? null : await scanSplits()), [asked]);
  const scanning = asked > 0 && scan.state === "loading";

  return (
    <section className="im-repair">
      <div className="im-repair-head">
        <button
          className="ag-btn"
          disabled={!enabled || scanning}
          onClick={() => {
            setApplied(0);
            setAsked((n) => n + 1);
          }}
          type="button"
        >
          {t("import.scan_splits")}
        </button>
        <p className="im-help">{t("import.scan_splits_help")}</p>
      </div>

      {applied > 0 && (
        <p className="im-ok">{t("import.toast_splits_applied", { n: applied })}</p>
      )}

      {asked > 0 && (
        <Loaded query={scan} skeleton={<Skeleton rows={3} />}>
          {(found) =>
            found === null ? null : found.splits.length === 0 ? (
              // A throttled scan answers with silence, so an empty list means
              // "could not tell" rather than "nothing missing" — and a clean
              // bill of health is the one thing it must not be read as.
              <p className={found.throttled ? "im-warn" : "im-ok"}>
                {t(
                  found.throttled
                    ? "common.data_unavailable"
                    : "import.scan_splits_clean",
                )}
              </p>
            ) : (
              <Found
                gaps={found.splits}
                onApplied={(n) => {
                  setApplied(n);
                  setAsked(0);
                  onApplied();
                }}
                onStale={() => setAsked((n) => n + 1)}
              />
            )
          }
        </Loaded>
      )}
    </section>
  );
}

function Found({
  gaps,
  onApplied,
  onStale,
}: {
  gaps: SplitGap[];
  onApplied: (n: number) => void;
  onStale: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const { on, picked, toggle } = useSelection(gaps.map(splitKey));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const chosen = gaps.filter((gap) => picked.includes(splitKey(gap)));

  /** The sentence that makes the case for one row, or nothing to make it with. */
  const evidence = (gap: SplitGap) =>
    gap.priced_at === null || gap.market_close === null
      ? NONE
      : t("import.split_evidence", {
          price: vocab.num(gap.priced_at, 2),
          date: gap.priced_on,
          close: vocab.num(gap.market_close, 2),
        });

  const shares = (value: number | null) =>
    value === null ? NONE : vocab.num(value, 4);

  const write = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const done = await applySplits(
        chosen.map((gap) => ({ ticker: gap.ticker, date: gap.date })),
      );
      onApplied(done.applied);
    } catch (error) {
      setFailed(true);
      // 409 is "this ledger is not missing that any more" — somebody applied it
      // elsewhere, or the book moved. Nothing was written, and the honest answer
      // is the current scan rather than the one on screen.
      if (error instanceof ApiError && error.status === 409) onStale();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="im-warn">{t("import.splits_found", { n: gaps.length })}</p>
      <div className="im-scroll">
        <table className="im-table">
          <thead>
            <tr>
              <th className="im-pick" scope="col" />
              <th scope="col">{vocab.column("ticker")}</th>
              <th scope="col">{vocab.column("date")}</th>
              <th scope="col">{vocab.column("ratio")}</th>
              <th className="im-num" scope="col">
                {vocab.column("held_before")}
              </th>
              <th className="im-num" scope="col">
                {vocab.column("held_after")}
              </th>
              <th scope="col">{vocab.column("evidence")}</th>
            </tr>
          </thead>
          <tbody>
            {gaps.map((gap) => {
              const key = splitKey(gap);
              return (
                <tr key={key}>
                  <td className="im-pick">
                    <input
                      // The symbol and the day are what the row is; a screen
                      // reader gets the same two words a sighted reader does.
                      aria-label={`${gap.ticker} ${gap.date}`}
                      checked={on(key)}
                      disabled={busy}
                      onChange={() => toggle(key)}
                      type="checkbox"
                    />
                  </td>
                  <td>
                    <TickerCell ticker={gap.ticker} />
                  </td>
                  <td>{gap.date}</td>
                  <td>{ratioLabel(gap.ratio)}</td>
                  <td className="im-num">{shares(gap.held_before)}</td>
                  <td className="im-num">{shares(gap.held_after)}</td>
                  <td className="im-issues">{evidence(gap)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {failed && <p className="im-bad">{t("common.failed")}</p>}
      <button
        className="ag-btn im-primary"
        disabled={busy || chosen.length === 0}
        onClick={write}
        type="button"
      >
        {t("import.apply_splits", { n: chosen.length })}
      </button>
      <p className="im-help">{t("import.apply_splits_help")}</p>
    </>
  );
}
