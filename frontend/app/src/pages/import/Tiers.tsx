/**
 * The three tiers, which are the safety property and not a presentation choice.
 *
 * `importable` is exactly what a commit writes. `rejected` failed validation
 * and is never committed — quarantined, and the reader has to fix it in the
 * export or add it by hand. `skipped` is what the parser leaves out by design:
 * cash movements, fees, tax corrections.
 *
 * All three are shown in full. A client that reported only counts would have
 * hidden the part a reader has to act on, which is the whole reason a bad
 * export cannot corrupt a cost basis here quietly.
 *
 * Warned rows appear twice on purpose, exactly as the Streamlit page shows
 * them: once among the rows that will be written, and again with their warning
 * spelled out, because a warning nobody reads is a warning that did not happen.
 */

import { useT } from "../../shell/i18n";
import type { Preview } from "./api";
import { Rich } from "./Rich";
import { RowTable, SkippedTable } from "./Tables";

export function Tiers({ preview }: { preview: Preview }) {
  const t = useT();
  const warned = preview.importable.filter((row) =>
    row.issues.some((issue) => issue.severity === "warning"),
  );
  const summary = t("import.preview_summary", {
    n: preview.importable.length,
    warned: warned.length,
    rejected: preview.rejected.length,
  });

  return (
    <section className="im-tiers">
      <h2 className="im-h2">{t("import.preview", { summary })}</h2>

      {preview.importable.length > 0 ? (
        <RowTable rows={preview.importable} />
      ) : (
        <p className="im-warn">{t("import.no_importable")}</p>
      )}

      {warned.length > 0 && (
        <>
          <p className="im-warn">
            {t("import.rows_with_warnings", { n: warned.length })}
          </p>
          <RowTable brief issues="warnings" rows={warned} />
        </>
      )}

      {preview.rejected.length > 0 && (
        <>
          <p className="im-bad">
            {t("import.rows_rejected", { n: preview.rejected.length })}
          </p>
          {/* No links: a rejected symbol is malformed by definition. */}
          <RowTable brief issues="errors" link={false} rows={preview.rejected} />
          <p className="im-help">
            <Rich text={t("import.rejected_help")} />
          </p>
        </>
      )}

      {preview.skipped.length > 0 && (
        <details className="im-details">
          <summary>{t("import.skipped_rows", { n: preview.skipped.length })}</summary>
          <SkippedTable rows={preview.skipped} />
          <p className="im-help">
            {t(
              preview.platform === "revolut"
                ? "import.skipped_caption_revolut"
                : "import.skipped_caption_generic",
            )}
          </p>
        </details>
      )}
    </section>
  );
}
