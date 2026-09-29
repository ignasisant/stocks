/**
 * Shares that only changed broker.
 *
 * No statement can say "these shares moved": the losing broker prints the
 * departure as a sale at the day's price and the receiving one prints the
 * arrival as a balance. Imported literally, that is a gain nobody made, a tax
 * bill nobody owes, and a holding period restarted for no reason.
 * `transfers.propose` finds the pairs from the one thing a sale and a
 * repurchase could not produce — an arrival carrying the basis the shares
 * already had — which is why every card below ends on that number.
 *
 * Unlike the split scan there is no button: this reads the ledger and, at most,
 * one ISIN lookup for a pair that already matches on everything else, so the
 * question is answered on every visit exactly as the Streamlit page answers it.
 * A book with nothing to repair says nothing at all.
 *
 * Two ways in. `Moves` asks the question itself — the chat drawer offers it
 * after a statement it imported. `MoveList` is handed the answer — the Import
 * page asks once for its rail card and for the phone banner that points to it.
 */

import { useState } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Status } from "../../ui/Status";
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
  const [again, setAgain] = useState(0);
  const scan = useApi(
    async () => (enabled ? await scanMoves() : { moves: [] }),
    [enabled, nonce, again],
  );
  const ask = () => setAgain((count) => count + 1);
  return (
    <MoveList
      moves={scan.state === "loaded" ? scan.data.moves : []}
      onApplied={() => {
        // Its own re-scan: the caller's counter need not move when a move is
        // booked, and the proposal on screen would outlive the rows it named.
        ask();
        onApplied();
      }}
      onStale={ask}
    />
  );
}

export function MoveList({
  moves,
  onApplied,
  onStale,
}: {
  /** What the scan proposes for the ledger as it stands. */
  moves: Move[];
  onApplied: () => void;
  /** The proposal on screen is not this ledger's any more: ask again. */
  onStale: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [applied, setApplied] = useState(0);

  if (applied === 0 && moves.length === 0) return null;
  return (
    <div className="im-repair">
      <div className="im-repair-head">
        <h3 className="im-h3">{t("import.moves_title")}</h3>
      </div>
      {applied > 0 && (
        <p className="im-ok">
          {t("import.toast_moves_applied", { n: vocab.num(applied, 0) })}
        </p>
      )}
      {moves.length > 0 && (
        <Found
          moves={moves}
          onApplied={(n) => {
            // No re-scan here: whoever asked the question asks it again.
            setApplied(n);
            onApplied();
          }}
          onStale={onStale}
        />
      )}
    </div>
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
      : `${move.phantom_gain > 0 ? "+" : ""}${vocab.num(move.phantom_gain, 2)} ${move.currency}`;

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
      <p className="im-fine">{t("import.moves_note")}</p>
      <div className="im-picks">
        {moves.map((move) => {
          const key = moveKey(move);
          return (
            <label className={on(key) ? "im-pick im-pick-on" : "im-pick"} key={key}>
              <input
                aria-label={`${move.ticker_in} ${move.date_out}`}
                checked={on(key)}
                className="im-pick-box"
                disabled={busy}
                onChange={() => toggle(key)}
                type="checkbox"
              />
              <span className="im-pick-body">
                <span className="im-pick-top">
                  {/* The receiving broker's label, which is the one that
                      survives: accepting renames the departure rows to it. */}
                  <TickerCell name={false} ticker={move.ticker_in} />
                  <span className="im-pick-q">
                    × {move.quantity === null ? NONE : vocab.num(move.quantity, 4)}
                  </span>
                  <span className="im-pick-date">{move.date_out}</span>
                </span>
                <span className="im-pick-line">
                  {move.broker_out} <span className="im-faint">→</span> {move.broker_in}
                  {" · "}
                  {vocab.column("gain")} <span className="im-loss">{gain(move)}</span>
                </span>
                {/* Never folded away, unlike a table's trailing columns: this
                    line is the evidence, and a reader is being asked to
                    believe it. */}
                <span className="im-pick-proof">{basis(move)}</span>
              </span>
            </label>
          );
        })}
      </div>
      {failed && <p className="im-bad">{t("common.failed")}</p>}
      <button
        className="im-btn im-btn-primary im-btn-block"
        disabled={busy || chosen.length === 0}
        onClick={write}
        type="button"
      >
        {chosen.length > 0
          ? t("import.apply_moves", { n: vocab.num(chosen.length, 0) })
          : t("import.pick_one")}
      </button>
      {busy && (
        <Status label={t("import.work_moves", { n: vocab.num(chosen.length, 0) })} />
      )}
      <p className="im-fine im-faint">{t("import.apply_moves_help")}</p>
    </>
  );
}
