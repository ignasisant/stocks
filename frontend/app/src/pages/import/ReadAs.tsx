/**
 * Who read the statement, said above the review, with the way to correct it.
 *
 * The reader no longer says whose statement it is: the file does. So the
 * reading has to be visible and cheap to overrule. A parser's reading says its
 * name and offers "not this one?" (a platform picked here is only the parser
 * tried first, and the same file is read again). The model's reading, for a
 * format no parser knows, shows which column it took for each field — the one
 * thing a reader can check at a glance before trusting the rows.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { note } from "./api";
import type { Platform, Preview } from "./api";

export function ReadAs({
  preview,
  platforms,
  override,
  onChange,
  onReplace,
}: {
  preview: Preview;
  platforms: Platform[];
  /** The platform the reader forced, "" when the file was left to say. */
  override: string;
  onChange: (key: string) => void;
  /** Open the file dialog for another statement. */
  onReplace: () => void;
}) {
  const t = useT();
  const [changing, setChanging] = useState(false);
  const columns = preview.columns ?? [];
  const byModel = preview.platform === "llm";
  const fresh = preview.new_positions ?? [];

  return (
    <section aria-label={t("import.read_label")} className="im-card im-readas">
      {byModel ? (
        <>
          <p className="im-readas-line">
            <strong>{t("import.read_ai_title")}</strong> {t("import.read_ai_body")}
          </p>
          {columns.length > 0 && (
            <ul className="im-readas-cols">
              {columns.map((entry) => (
                <li key={entry.field}>
                  <span className="im-readas-field">
                    {t.has(`import.field_${entry.field}`)
                      ? t(`import.field_${entry.field}`)
                      : entry.field}
                  </span>
                  <span className="im-readas-col">{entry.column}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="im-readas-actions">
            <button
              className="im-btn im-btn-outline"
              onClick={() => {
                note("replace", "", preview.digest);
                onReplace();
              }}
              type="button"
            >
              {t("import.read_other_file")}
            </button>
          </div>
        </>
      ) : (
        <p className="im-readas-line">
          {t("import.read_as_line", { label: preview.label || preview.platform })}{" "}
          {!changing && (
            <button className="im-link" onClick={() => setChanging(true)} type="button">
              {t("import.read_not_this")}
            </button>
          )}
          {changing && (
            <select
              aria-label={t("import.read_pick")}
              className="im-readas-select"
              onChange={(event) => {
                note(
                  "override",
                  `${preview.platform}>${event.target.value || "auto"}`,
                  preview.digest,
                );
                onChange(event.target.value);
                setChanging(false);
              }}
              value={override}
            >
              <option value="">{t("import.read_auto")}</option>
              {platforms.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.label}
                </option>
              ))}
            </select>
          )}
        </p>
      )}
      {fresh.length > 0 && (
        <p className="im-fine">
          {t("import.read_new_positions", {
            n: fresh.length,
            names: fresh.slice(0, 5).join(", "),
          })}
        </p>
      )}
    </section>
  );
}
