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
 * Then the commit, which re-parses and re-validates rather than trusting the
 * preview: the ledger is shared mutable state, and a row that was importable
 * ten seconds ago can be a duplicate now. `expect` carries the preview's digest
 * so a file that changed underneath the reader is refused instead of committed
 * as something nobody ever saw.
 */

import { useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { useAccount } from "../../shell/session";
import { MAX_BYTES, commit } from "./api";
import type { Platform, Preview, Refusal, Result, Staged } from "./api";
import { names } from "./repairs";
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
  platform,
  platforms,
  staged,
  preview,
  wipe,
  onCommitted,
}: {
  platform: Platform;
  platforms: Platform[];
  staged: Staged;
  preview: Preview;
  /** Replace the book rather than add to it, and the address that confirms it. */
  wipe: WipeChoice;
  onCommitted: (result: Result) => void;
}) {
  const t = useT();
  const me = useAccount();
  const options = useMemo(() => brands(platforms), [platforms]);
  const [pick, setPick] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  // Naming the real broker beats "other", so a typed name wins over the
  // catch-all when both are present.
  const chosen = pick === OTHER ? typed.trim() || OTHER : pick;
  const origin = preview.needs_broker ? chosen : "";
  const ready =
    preview.importable.length > 0 &&
    (!preview.needs_broker || origin !== "") &&
    // A wipe that is asked for and not confirmed is refused by the route with a
    // 422; pressing the button to learn that would be a press that might have
    // emptied the book.
    (!wipe.on || names(wipe.confirm, me.email ?? ""));

  const write = async () => {
    setBusy(true);
    setRefusal(null);
    try {
      const outcome = await commit(platform.key, staged, origin, preview.digest, wipe);
      if (outcome.ok) onCommitted(outcome.value);
      else setRefusal(outcome.refusal);
    } catch {
      // Not a refusal the API spelled out — the ledger is untouched either way.
      setRefusal({ kind: "refused", detail: "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="im-commit">
      {preview.needs_broker && (
        <div className="im-field">
          <label className="im-label" htmlFor="im-broker">
            {t("import.broker")}
          </label>
          <select
            className="im-input"
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
              aria-label={t("import.broker_other")}
              className="im-input"
              onChange={(event) => setTyped(event.target.value)}
              type="text"
              value={typed}
            />
          )}
          <p className="im-help">{t("import.broker_help")}</p>
        </div>
      )}

      <button
        className="ag-btn im-primary"
        disabled={!ready || busy}
        onClick={write}
        type="button"
      >
        {t("import.commit_button")}
      </button>

      {refusal && (
        <p className="im-bad">
          {refusal.kind === "changed"
            ? t("import.file_changed")
            : refusal.kind === "too_large"
              ? t("import.file_too_large", {
                  size: (staged.bytes / (1024 * 1024)).toFixed(1),
                  cap: MAX_BYTES / (1024 * 1024),
                })
              : t("import.commit_failed")}
        </p>
      )}
    </section>
  );
}
