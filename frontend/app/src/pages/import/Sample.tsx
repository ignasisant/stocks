/**
 * The empty book's card, and the shipped example statement inside it.
 *
 * It is drawn on the empty path only. An account that already holds a real
 * ledger has no use for the example, and a button that adds somebody else's
 * trades to a real book is a trap rather than a tour — the server cannot tell
 * those apart, says so, and leaves the rule here.
 *
 * The bytes go into the same staging slot a file picker fills, so the example
 * rides the identical path: parse, validate, tiered preview, commit,
 * last-import record, undo. A separate "load the demo" route would be the thing
 * that drifts from the real one, and would teach a flow nobody uses twice.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { Status } from "../../ui/Status";
import { sampleStatement } from "./api";
import type { Platform } from "./api";

export function Sample({
  platform,
  onPicked,
}: {
  platform: Platform;
  /** The same handler the file input uses — there is no second path in. */
  onPicked: (filename: string, blob: Blob) => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  // A trimmed deployment ships without the file, and the honest answer to that
  // is silence: the offer removes itself rather than failing in the reader's
  // face over something they cannot fix. The card stays — it still says where
  // this platform's statement is found.
  const [gone, setGone] = useState(false);
  const offer = platform.has_sample && !gone;

  const load = async () => {
    setBusy(true);
    const file = await sampleStatement(platform.key);
    setBusy(false);
    if (!file) {
      setGone(true);
      return;
    }
    // The extension is what picks the branch inside a parser, so a response
    // that named no file falls back to this platform's first format rather
    // than to a guess.
    onPicked(file.filename || `sample.${platform.file_types[0] ?? "csv"}`, file.blob);
  };

  return (
    <section aria-labelledby="im-empty-title" className="im-card im-empty">
      <h2 className="im-h3" id="im-empty-title">
        {t("import.empty_title")}
      </h2>
      <p className="im-fine">
        {platform.hint}
        {offer ? ` ${t("import.sample_short")}` : null}
      </p>
      {offer && (
        <button
          className="im-btn im-btn-outline"
          disabled={busy}
          onClick={load}
          type="button"
        >
          {t("import.sample_button")}
        </button>
      )}
      {busy && <Status label={t("import.work_sample")} />}
    </section>
  );
}
