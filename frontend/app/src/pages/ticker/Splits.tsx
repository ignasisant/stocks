/**
 * A split the book never heard about, repaired on the page that shows it.
 *
 * A broker statement prints trades, not corporate actions: one AMZN bought at
 * $2050 before the 2022 20-for-1 arrives as one share at $2050, and the page
 * then reads a $378 average against a $250 price. The evidence is this page's
 * own — that buy price is twenty times the close of its day — so the page asks
 * the server for the gap (`GET /ticker/{symbol}/splits`) and writes it straight
 * away, through the edit journal. What it did is said in one line with an
 * undo beside it, because a repair nobody asked for has to be one click from
 * gone.
 *
 * A split the reader undid comes back `declined` and is never written again
 * unasked: the line stays, with the button that applies it.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApi } from "../../shell/useApi";
import { useGuest } from "../../shell/session";
import { useT } from "../../shell/i18n";
import { applySplits, getSplits, undoChange } from "./data";
import { money, shares } from "./format";
import type { TickerPosition, TickerSplit } from "./types";

export type Done =
  | { kind: "applied"; changeId: number; splits: TickerSplit[] }
  | { kind: "undone"; splits: TickerSplit[] }
  | { kind: "failed"; splits: TickerSplit[] };

export function SplitRepair({
  ticker,
  position,
  onChanged,
}: {
  ticker: string;
  position: TickerPosition | null;
  /** The book changed: re-ask for the position. */
  onChanged: () => void;
}) {
  const t = useT();
  const guest = useGuest();
  // Latched per company: the position re-fetches after a repair and reads as
  // null while it does, which must not re-run the scan in between.
  const [bought, setBought] = useState<string | null>(null);
  const buys = Boolean(position?.trades.some((fill) => fill.action === "buy"));
  useEffect(() => {
    if (buys) setBought(ticker);
  }, [buys, ticker]);
  const scan = useApi(
    () => (bought === ticker && !guest ? getSplits(ticker) : Promise.resolve(null)),
    [ticker, bought, guest],
  );

  const [done, setDone] = useState<Done | null>(null);
  const [busy, setBusy] = useState(false);
  const tried = useRef<string | null>(null);
  useEffect(() => setDone(null), [ticker]);

  const apply = (splits: TickerSplit[]) => {
    setBusy(true);
    applySplits(
      ticker,
      splits.map((split) => split.date),
    )
      .then(
        (written) => {
          setDone({
            kind: "applied",
            changeId: written.change_id,
            splits: written.splits,
          });
          onChanged();
        },
        () => setDone({ kind: "failed", splits }),
      )
      .finally(() => setBusy(false));
  };

  const undo = (changeId: number, splits: TickerSplit[]) => {
    setBusy(true);
    undoChange(changeId)
      .then(
        () => {
          setDone({ kind: "undone", splits });
          onChanged();
        },
        () => undefined,
      )
      .finally(() => setBusy(false));
  };

  // Once per company per visit: what the reader has not refused is written.
  const found = useMemo(
    () => (scan.state === "loaded" && scan.data ? scan.data.splits : []),
    [scan],
  );
  useEffect(() => {
    if (tried.current === ticker) return;
    const fresh = unrefused(found);
    if (fresh.length === 0) return;
    tried.current = ticker;
    apply(fresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [found, ticker]);

  if (done?.kind === "applied") {
    return (
      <Line text={done.splits.map((split) => applied(t, split)).join(" ")}>
        <button
          type="button"
          className="ag-btn"
          disabled={busy}
          onClick={() => undo(done.changeId, done.splits)}
        >
          {t("ticker.split_undo")}
        </button>
      </Line>
    );
  }
  const pending = offered(done, found);
  if (pending.length === 0) return null;
  const why =
    done?.kind === "failed" ? t("ticker.split_failed") : t("ticker.split_declined");
  return (
    <Line text={[...pending.map((split) => missing(t, split)), why].join(" ")}>
      <button
        type="button"
        className="ag-btn"
        disabled={busy}
        onClick={() => apply(pending)}
      >
        {t("ticker.split_apply")}
      </button>
    </Line>
  );
}

/** What the page writes unasked: every gap the reader has not undone before. */
export function unrefused(found: TickerSplit[]): TickerSplit[] {
  return found.filter((split) => !split.declined);
}

/** What waits behind the apply button, once nothing is applied right now. */
export function offered(done: Done | null, found: TickerSplit[]): TickerSplit[] {
  if (done?.kind === "applied") return [];
  if (done?.kind === "undone" || done?.kind === "failed") return done.splits;
  return found.filter((split) => split.declined);
}

type Translate = ReturnType<typeof useT>;

export function fields(split: TickerSplit) {
  return {
    ratio: `${split.ratio}`,
    date: split.date,
    price: money(split.priced_at),
    day: split.priced_on,
    adjusted: money(split.priced_at / split.ratio),
    before: shares(split.held_before),
    after: shares(split.held_after),
    currency: split.currency,
  };
}

function applied(t: Translate, split: TickerSplit): string {
  return t("ticker.split_applied", fields(split));
}

function missing(t: Translate, split: TickerSplit): string {
  return t("ticker.split_missing", fields(split));
}

function Line({ text, children }: { text: string; children: ReactNode }) {
  return (
    <div className="tk-split" role="status">
      <p>{text}</p>
      {children}
    </div>
  );
}
