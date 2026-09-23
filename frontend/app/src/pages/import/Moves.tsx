/**
 * Shares that only changed broker.
 *
 * No statement can say "these shares moved": the losing broker prints the
 * departure as a sale at the day's price and the receiving one prints the
 * arrival as a balance. Imported literally, that is a gain nobody made, a tax
 * bill nobody owes, and a holding period restarted for no reason.
 * `transfers.propose` finds the pairs from the one thing a sale and a
 * repurchase could not produce — an arrival carrying the basis the shares
 * already had — which is why the table below leads on that number.
 *
 * Unlike the split scan there is no button: this reads the ledger and, at most,
 * one ISIN lookup for a pair that already matches on everything else, so the
 * question is answered on every visit exactly as the Streamlit page answers it.
 * A book with nothing to repair says nothing at all — including while the
 * answer is still coming, because nobody asked for it.
 */

import { useState } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { applyMoves, scanMoves } from "./api";
import type { Move } from "./api";
import { moveKey, useSelection } from "./repairs";
import { useVocabulary } from "./text";

/** A figure the scan could not put a number on. Never rendered as a zero. */
const NONE = "—";

export function Moves({
  enabled,
  nonce,
  onApplied,
}: {
  /** False for a book with no real rows: there are no pairs to find. */
  enabled: boolean;
  /** Bumped by anything that writes — the proposals are about that ledger. */
  nonce: number;
  onApplied: () => void;
}) {
  const t = useT();
  const [applied, setApplied] = useState(0);
  const [again, setAgain] = useState(0);
  const scan = useApi(
    async () => (enabled ? await scanMoves() : { moves: [] }),
    [enabled, nonce, again],
  );
  const moves = scan.state === "loaded" ? scan.data.moves : [];

  if (applied === 0 && moves.length === 0) return null;
  return (
    <section className="im-repair">
      {applied > 0 && (
        <p className="im-ok">{t("import.toast_moves_applied", { n: applied })}</p>
      )}
      {moves.length > 0 && (
        <Found
          moves={moves}
          onApplied={(n) => {
            // No local re-scan: recording a move writes, so the page bumps
            // `nonce` and this query re-runs once rather than twice.
            setApplied(n);
            onApplied();
          }}
          onStale={() => setAgain((count) => count + 1)}
        />
      )}
    </section>
  );
}

function Found({
  moves,
  onApplied,
  onStale,
}: {
  moves: Move[];
  onApplied: (n: number) => void;
  onStale: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const { on, picked, toggle } = useSelection(moves.map(moveKey));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const chosen = moves.filter((move) => picked.includes(moveKey(move)));

  /** What the book currently reports for shares nobody sold. */
  const gain = (move: Move) =>
    move.phantom_gain === null
      ? NONE
      : t("import.move_gain", {
          amount: `${vocab.num(move.phantom_gain, 2)} ${move.currency}`,
        });

  /** The evidence itself: the cost that arrived, against the price it was sold
   *  at. A real sale and repurchase would report the repurchase price. */
  const basis = (move: Move) =>
    move.basis_in === null || move.booked_at === null
      ? NONE
      : t("import.move_basis", {
          basis: vocab.num(move.basis_in, 2),
          sold: vocab.num(move.booked_at, 2),
        });

  const write = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const done = await applyMoves(
        chosen.map((move) => ({ out_ids: move.out_ids, in_id: move.in_id })),
      );
      onApplied(done.applied);
    } catch (error) {
      setFailed(true);
      // 409 means these rows are not a move this ledger proposes any more.
      // Nothing was written; the fresh proposal replaces the stale one.
      if (error instanceof ApiError && error.status === 409) onStale();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="im-warn">{t("import.moves_found", { n: moves.length })}</p>
      <div className="im-scroll">
        <table className="im-table">
          <thead>
            <tr>
              <th className="im-pick" scope="col" />
              <th scope="col">{vocab.column("ticker")}</th>
              <th className="im-num" scope="col">
                {vocab.column("quantity")}
              </th>
              <th scope="col">{vocab.column("from")}</th>
              <th scope="col">{vocab.column("to")}</th>
              <th scope="col">{vocab.column("date")}</th>
              <th scope="col">{vocab.column("gain")}</th>
              {/* Never folded away on a phone, unlike the trailing columns of
                  the preview tables: this column is the evidence, and a reader
                  is being asked to believe it. */}
              <th scope="col">{vocab.column("basis")}</th>
            </tr>
          </thead>
          <tbody>
            {moves.map((move) => {
              const key = moveKey(move);
              return (
                <tr key={key}>
                  <td className="im-pick">
                    <input
                      aria-label={`${move.ticker_in} ${move.date_out}`}
                      checked={on(key)}
                      disabled={busy}
                      onChange={() => toggle(key)}
                      type="checkbox"
                    />
                  </td>
                  <td>
                    {/* The receiving broker's label, which is the one that
                        survives: accepting renames the departure rows to it. */}
                    <TickerCell ticker={move.ticker_in} />
                  </td>
                  <td className="im-num">
                    {move.quantity === null ? NONE : vocab.num(move.quantity, 4)}
                  </td>
                  <td>{move.broker_out}</td>
                  <td>{move.broker_in}</td>
                  <td>{move.date_out}</td>
                  <td>{gain(move)}</td>
                  <td className="im-issues">{basis(move)}</td>
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
        {t("import.apply_moves", { n: chosen.length })}
      </button>
      <p className="im-help">{t("import.apply_moves_help")}</p>
    </>
  );
}
