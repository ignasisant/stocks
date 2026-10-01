/**
 * Naming the origin, and writing the rows.
 *
 * Attribution first: every broker parser stamps its own name as the note's
 * first word, and the Fees and Custody views read the book by that word. A
 * generic ledger CSV can come from anywhere and stamps nothing, so `broker` is
 * asked for before the commit button becomes pressable — a batch committed
 * unattributed lands under whatever its notes happened to start with and is
 * tedious to fix afterwards.
 *
 * Then the commit, which sends the rows the preview showed and has them
 * re-validated rather than trusting its verdict: the ledger is shared mutable
 * state, and a row that was importable ten seconds ago can be a duplicate now.
 * The rows, not the file, because the model that read the file may not read it
 * the same way twice — what is written is exactly what was reviewed.
 *
 * It is drawn as a bar pinned over the tiers — to the top of the screen beside
 * a wide table, to the bottom on a phone — so the one press the page exists for
 * never scrolls away. The broker question sits just above it, unpinned. A button that cannot be pressed yet says why underneath;
 * a disabled control with no reason reads as a broken one.
 */

import { useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { useAccount } from "../../shell/session";
import { Status } from "../../ui/Status";
import { MAX_BYTES, commit } from "./api";
import type { Platform, Preview, Refusal, Result, Staged } from "./api";
import { Eyebrow } from "./Card";
import { names } from "./repairs";
import { Rich } from "./Rich";
import { useVocabulary } from "./text";
import type { WipeChoice } from "./Wipe";

/** `platforms.OTHER` — a real origin, just not one the registry parses. */
const OTHER = "other";

/**
 * Brands the ledger already knows by name, read off the platform registry.
 *
 * A platform that declares a domain is a broker; the generic CSV format
 * declares none. Two entries can share one brand (Revolut stocks and Revolut
 * crypto), and the origin is one word, so the domain deduplicates them. The
 * option's value is the platform key, which is the exact word the ledger
 * stores and the Fees view groups by — a typed-in label would normalise to a
 * different word for the same broker.
 */
function brands(platforms: Platform[]): Platform[] {
  const seen = new Set<string>();
  return platforms.filter((platform) => {
    if (!platform.domain || seen.has(platform.domain)) return false;
    seen.add(platform.domain);
    return true;
  });
}

export function CommitPanel({
  platforms,
  staged,
  preview,
  wipe,
  onCommitted,
}: {
  platforms: Platform[];
  staged: Staged;
  preview: Preview;
  /** Replace the book rather than add to it, and the address that confirms it. */
  wipe: WipeChoice;
  onCommitted: (result: Result) => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const me = useAccount();
  const options = useMemo(() => brands(platforms), [platforms]);
  const [pick, setPick] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const rows = preview.importable.length;
  const rejected = preview.rejected.length;
  const skipped = preview.skipped.length;

  // Naming the real broker beats "other", so a typed name wins over the
  // catch-all when both are present.
  const chosen = pick === OTHER ? typed.trim() || OTHER : pick;
  const origin = preview.needs_broker ? chosen : "";
  // The first thing still missing, in the order a reader would fix them. A
  // wipe that is asked for and not confirmed is refused by the route with a
  // 422; pressing the button to learn that would be a press that might have
  // emptied the book.
  const missing =
    rows === 0
      ? t("import.no_importable")
      : preview.needs_broker && origin === ""
        ? t("import.broker_missing")
        : wipe.on && !names(wipe.confirm, me.email ?? "")
          ? t("import.commit_needs_email")
          : null;

  const write = async () => {
    setBusy(true);
    setRefusal(null);
    try {
      const outcome = await commit(preview, staged, origin, wipe);
      if (outcome.ok) onCommitted(outcome.value);
      else setRefusal(outcome.refusal);
    } catch {
      // Not a refusal the API spelled out — the ledger is untouched either way.
      setRefusal({ kind: "refused", detail: "" });
    } finally {
      setBusy(false);
    }
  };

  // What the commit leaves behind, said beside what it writes: the tiers below
  // are the detail, this is the sentence a reader decides on.
  const left =
    rejected > 0 && skipped > 0
      ? t("import.confirm_left_both", {
          rejected: vocab.num(rejected, 0),
          skipped: vocab.num(skipped, 0),
        })
      : rejected > 0
        ? t("import.confirm_left_rejected", { n: vocab.num(rejected, 0) })
        : skipped > 0
          ? t("import.confirm_left_skipped", { n: vocab.num(skipped, 0) })
          : "";

  return (
    <>
      {/* Above the pinned bar rather than inside it: the question, its field
          and its help are three lines, and a bar that tall pinned to a phone's
          foot would cover half the rows it is asking about. */}
      {preview.needs_broker && (
        <div className="im-broker">
          <label className="im-label" htmlFor="im-broker">
            {t("import.broker")}
          </label>
          <div className="im-broker-row">
            <select
              className="im-input"
              disabled={busy}
              id="im-broker"
              onChange={(event) => setPick(event.target.value)}
              value={pick}
            >
              <option value="">{t("import.broker_pick")}</option>
              {options.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
              <option value={OTHER}>{t("import.broker_other")}</option>
            </select>
            {pick === OTHER && (
              <input
                aria-label={t("import.broker_name")}
                className="im-input"
                disabled={busy}
                onChange={(event) => setTyped(event.target.value)}
                placeholder={t("import.broker_name")}
                type="text"
                value={typed}
              />
            )}
          </div>
          <p className="im-fine">{t("import.broker_help")}</p>
        </div>
      )}
      <div aria-label={t("import.confirm")} className="im-confirm" role="region">
        <div className="im-confirm-main">
          <div className="im-confirm-text">
            <Eyebrow n={4}>{t("import.confirm")}</Eyebrow>
            {busy ? (
              <Status label={vocab.tn("import.work_committing", rows)} />
            ) : (
              <>
                <span className="im-confirm-long">
                  <Rich text={vocab.tn("import.confirm_rows", rows)} /> {left}
                </span>
                <span className="im-confirm-short">
                  <strong>{vocab.tn("import.rows_count", rows)}</strong>
                  {rejected > 0 && (
                    <small>{vocab.tn("import.rejected_left", rejected)}</small>
                  )}
                </span>
              </>
            )}
          </div>
          <button
            className="im-btn im-btn-primary im-btn-go"
            disabled={missing !== null || busy}
            onClick={write}
            type="button"
          >
            <span className="im-confirm-long">{t("import.confirm_button")}</span>
            <span className="im-confirm-short">{t("import.confirm_short")}</span>
          </button>
        </div>

        {missing && !busy && <p className="im-line-warn">{missing}</p>}

        {refusal && (
          <div className="im-line-bad" role="alert">
            <p>
              {refusal.kind === "changed"
                ? t("import.file_changed")
                : refusal.kind === "too_large"
                  ? t("import.file_too_large", {
                      size: (staged.bytes / (1024 * 1024)).toFixed(1),
                      cap: MAX_BYTES / (1024 * 1024),
                    })
                  : t("import.commit_failed")}
            </p>
            <p>{t("import.nothing_written")}</p>
          </div>
        )}
      </div>
    </>
  );
}
