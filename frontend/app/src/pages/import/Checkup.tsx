/**
 * What the book can fix now, besides moves and splits (`GET /import/checkup`).
 *
 * Four kinds, all read from the ledger so it loads with the card:
 *
 * * sales an import held back for want of shares, which a split or transfer
 *   written since now covers — ticked, and written on a press;
 * * statements worth uploading again: a split was written after them on a name
 *   they still show open, so a sale refused then may be recoverable. Uploading
 *   is safe (what the book has is dropped as a duplicate);
 * * the doctor's findings that carry their fix — one name under two labels, a
 *   trade imported from two brokers, a Revolut fee left in the coins;
 * * the repairs the app made by itself, each with its Undo. Undone, a repair is
 *   never written again.
 *
 * Every apply names what it accepts and the server rebuilds it from a scan of
 * its own, so a stale card is a 409 and a fresh look, never a wrong write.
 */

import { useEffect, useState } from "react";
import { ApiError } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { toast } from "../../ui/toast";
import {
  applyFix,
  applyHeld,
  checkup,
  dismissReupload,
  type Checkup as Found,
  type Finding,
  type Healed,
  type HeldSale,
  type ReuploadHint,
  undoChange,
} from "./api";
import { useSelection } from "./repairs";
import { useVocabulary } from "./text";

/** How many entries ask the reader for something — the rail's badge. */
const waitingIn = (found: Found): number =>
  found.held.length + found.reupload.length + found.findings.length;

export function Checkup({
  nonce,
  onApplied,
  onFound,
}: {
  /** Bumped by every write on the page; the checkup reads the ledger again. */
  nonce: number;
  onApplied: () => void;
  onFound: (n: number) => void;
}) {
  const [again, setAgain] = useState(0);
  const query = useApi(() => checkup(), [nonce, again], { keep: true });
  const waiting = query.state === "loaded" ? waitingIn(query.data) : 0;
  useEffect(() => onFound(waiting), [waiting, onFound]);

  const refresh = () => setAgain((n) => n + 1);
  const done = () => {
    refresh();
    onApplied();
  };

  // A side panel of the repairs card: while it loads, or if it fails, the
  // card shows what it has rather than a skeleton or an error of its own.
  if (query.state !== "loaded") return null;
  const found = query.data;
  if (waiting === 0 && found.healed.length === 0) return null;
  return (
    <>
      <hr className="im-rule" />
      {found.held.length > 0 && (
        <Held onApplied={done} onStale={refresh} sales={found.held} />
      )}
      {found.reupload.map((hint) => (
        <Reupload hint={hint} key={hint.key} onDone={refresh} />
      ))}
      {found.findings.map((finding) => (
        <Fix finding={finding} key={finding.key} onApplied={done} onStale={refresh} />
      ))}
      {found.healed.map((healed) => (
        <HealedLine healed={healed} key={healed.change_id} onUndone={done} />
      ))}
    </>
  );
}

function Held({
  sales,
  onApplied,
  onStale,
}: {
  sales: HeldSale[];
  onApplied: () => void;
  onStale: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const key = (sale: HeldSale) => String(sale.id);
  const { on, picked, toggle } = useSelection(sales.map(key));
  const [busy, setBusy] = useState(false);

  const write = async () => {
    setBusy(true);
    try {
      const done = await applyHeld(picked.map(Number));
      toast.ok(vocab.tn("import.toast_held_applied", done.applied));
      onApplied();
    } catch (error) {
      toast.bad(t("common.failed"));
      if (error instanceof ApiError && error.status === 409) onStale();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="im-repair">
      <div className="im-repair-head">
        <h2 className="im-h3">{t("import.held_title")}</h2>
        <span className="im-tag">{t("import.proposal")}</span>
      </div>
      <p className="im-fine">{t("import.held_note")}</p>
      <div className="im-picks">
        {sales.map((sale) => (
          <label
            className={on(key(sale)) ? "im-pick im-pick-on" : "im-pick"}
            key={sale.id}
          >
            <input
              aria-label={`${sale.ticker} ${sale.date}`}
              checked={on(key(sale))}
              className="im-pick-box"
              disabled={busy}
              onChange={() => toggle(key(sale))}
              type="checkbox"
            />
            <span className="im-pick-body">
              <span className="im-pick-top">
                <TickerCell name={false} ticker={sale.ticker} />
                <span className="im-pick-q">{vocab.num(sale.quantity, 4)}</span>
                <span className="im-pick-date">{sale.date}</span>
              </span>
              <span className="im-pick-line">
                {t("import.held_line", {
                  price: vocab.num(sale.price, 2),
                  currency: sale.currency,
                  broker: sale.broker,
                })}
              </span>
            </span>
          </label>
        ))}
      </div>
      <button
        className="im-btn im-btn-primary im-btn-block"
        disabled={busy || picked.length === 0}
        onClick={write}
        type="button"
      >
        {picked.length > 0
          ? vocab.tn("import.apply_held", picked.length)
          : t("import.pick_one")}
      </button>
    </div>
  );
}

function Reupload({ hint, onDone }: { hint: ReuploadHint; onDone: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const hide = async () => {
    setBusy(true);
    try {
      await dismissReupload(hint.key);
      onDone();
    } catch {
      toast.bad(t("common.failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="im-repair im-fix">
      <div className="im-fix-text">
        <h2 className="im-h3">{t("import.reupload_title", { broker: hint.broker })}</h2>
        <p className="im-fine">
          {t("import.reupload_note", { ticker: hint.ticker, date: hint.split_date })}
        </p>
      </div>
      <button
        className="im-btn im-btn-text"
        disabled={busy}
        onClick={hide}
        type="button"
      >
        {t("import.hide")}
      </button>
    </div>
  );
}

/** One sentence saying what a finding is, from the facts the doctor kept. */
function useDescribe() {
  const t = useT();
  const vocab = useVocabulary();
  return (finding: Finding): string => {
    const d = finding.detail;
    switch (finding.kind) {
      case "two_labels":
        return t("import.fix_two_labels", {
          labels: ((d.labels as string[]) ?? []).join(" · "),
          ticker: finding.ticker,
        });
      case "duplicate":
        return t("import.fix_duplicate", {
          date: String(d.date ?? ""),
          quantity: vocab.num(Number(d.quantity ?? 0), 4),
          kept: String(d.broker_kept ?? ""),
          dropped: String(d.broker_dropped ?? ""),
        });
      case "fee_in_coins":
        return vocab.tn("import.fix_fee_in_coins", Number(d.buys ?? 0));
      default:
        return finding.kind;
    }
  };
}

function Fix({
  finding,
  onApplied,
  onStale,
}: {
  finding: Finding;
  onApplied: () => void;
  onStale: () => void;
}) {
  const t = useT();
  const describe = useDescribe();
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const done = await applyFix(finding.key);
      toast.ok(t("import.toast_fixed"), {
        action: {
          label: t("import.undo"),
          onClick: () => void undoChange(done.change_id).then(onApplied),
        },
      });
      onApplied();
    } catch (error) {
      toast.bad(t("common.failed"));
      if (error instanceof ApiError && error.status === 409) onStale();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="im-repair im-fix">
      <div className="im-fix-text">
        <h2 className="im-h3">
          <TickerCell name={false} ticker={finding.ticker} />
        </h2>
        <p className="im-fine">{describe(finding)}</p>
      </div>
      <button
        className="im-btn im-btn-outline im-btn-sm"
        disabled={busy}
        onClick={apply}
        type="button"
      >
        {t("import.fix")}
      </button>
    </div>
  );
}

function HealedLine({ healed, onUndone }: { healed: Healed; onUndone: () => void }) {
  const t = useT();
  const vocab = useVocabulary();
  const [busy, setBusy] = useState(false);
  const undo = async () => {
    setBusy(true);
    try {
      await undoChange(healed.change_id);
      toast.ok(t("import.toast_undone"));
      onUndone();
    } catch {
      toast.bad(t("common.failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="im-repair im-fix">
      <p className="im-line-ok im-fix-text">
        ✓ {vocab.tn(`import.healed_${healed.kind}`, healed.rows)}
      </p>
      <button
        className="im-btn im-btn-text"
        disabled={busy}
        onClick={undo}
        type="button"
      >
        {t("import.undo")}
      </button>
    </div>
  );
}
