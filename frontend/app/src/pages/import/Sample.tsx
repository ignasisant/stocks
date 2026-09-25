/**
 * The shipped example statement, for a reader with nothing to import.
 *
 * It is offered on the empty path only. An account that already holds a real
 * ledger has no use for it, and a button that adds somebody else's trades to a
 * real book is a trap rather than a tour — the server cannot tell those apart,
 * says so, and leaves the rule here.
 *
 * The bytes go into the same staging slot a file picker fills, so the example
 * rides the identical path: parse, validate, tiered preview, commit,
 * last-import record, undo. A separate "load the demo" route would be the thing
 * that drifts from the real one, and would teach a flow nobody uses twice.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
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
  // face over something they cannot fix.
  const [gone, setGone] = useState(false);

  if (!platform.has_sample || gone) return null;

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
    <div className="im-sample">
      <p className="im-help">
        {t("import.sample_caption", { platform: platform.label })}
      </p>
      <button className="ag-btn" disabled={busy} onClick={load} type="button">
        {t("import.sample_button")}
      </button>
    </div>
  );
}
