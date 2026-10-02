/**
 * Steps one and two in one card: which broker, and its statement.
 *
 * They share a card because they are one decision — a statement means nothing
 * until the parser that reads it is chosen, and changing the platform discards
 * a staged file for exactly that reason. What rides along sits on the card's
 * last line: the paste box for a browser that will not hand over a file, and
 * the wipe, which has to be decided before the preview is read, not after.
 *
 * The handlers are the page's (`Import.tsx`), because the staged file is the
 * preview's identity; this only draws them.
 */

import { useState } from "react";
import type { ChangeEvent, DragEvent, FocusEvent, ReactNode, RefObject } from "react";
import { useT } from "../../shell/i18n";
import { MAX_BYTES, acceptOf } from "./api";
import type { Platform, Staged } from "./api";
import { Eyebrow } from "./Card";
import { Glyph } from "./Glyph";

export function Source({
  platforms,
  accepts,
  platform,
  onChoose,
  staged,
  dragging,
  onDragging,
  onPick,
  onDrop,
  onPaste,
  file,
  errors,
  hint,
  wipe,
}: {
  platforms: Platform[];
  /** Every extension a statement can arrive as — not only this platform's. */
  accepts: string[];
  platform: Platform;
  onChoose: (key: string) => void;
  staged: Staged | null;
  /** A file is held over the zone, which lights it up as a target. */
  dragging: boolean;
  onDragging: (over: boolean) => void;
  onPick: (event: ChangeEvent<HTMLInputElement>) => void;
  onDrop: (event: DragEvent<HTMLLabelElement>) => void;
  onPaste: (event: FocusEvent<HTMLTextAreaElement>) => void;
  file: RefObject<HTMLInputElement | null>;
  /** What went wrong reading the statement, one sentence each. */
  errors: string[];
  /** Say where this platform's statement is found. */
  hint: boolean;
  /** The wipe's tick and, once ticked, its confirmation. */
  wipe: ReactNode;
}) {
  const t = useT();
  const [pasting, setPasting] = useState(false);
  const types = accepts.map((kind) => kind.toUpperCase()).join(", ");
  const cap = t("import.drop_caption", { cap: MAX_BYTES / (1024 * 1024), types });
  // A pasted statement has no file name to show, and the zone keeps offering a
  // file for it: the paste box below is where that text lives.
  const chosen = staged && staged.surface !== "paste" ? staged : null;

  return (
    <section aria-labelledby="im-platform" className="im-card im-source">
      <div className="im-block">
        <div className="im-eyebrow-row">
          <Eyebrow id="im-platform" n={1}>
            {t("import.step_platform")}
          </Eyebrow>
          {/* The address the choice lives at, so a link can land on it. */}
          <span className="im-param">?platform={platform.key}</span>
        </div>
        {/* One control at every width. Seven brand names do not fit a phone
            row side by side, which is why the Streamlit page falls back to a
            dropdown there; letting them wrap solves the same problem without
            a second control to keep in step. */}
        <div aria-labelledby="im-platform" className="im-chips" role="group">
          {platforms.map((entry) => (
            <button
              aria-pressed={entry.key === platform.key}
              className={entry.key === platform.key ? "im-chip im-chip-on" : "im-chip"}
              key={entry.key}
              onClick={() => onChoose(entry.key)}
              type="button"
            >
              {/* The brand mark over its initial, so a logo that fails to load
                  leaves a letter rather than a hole. Decorative either way:
                  the name beside it is the label. */}
              <span aria-hidden="true" className="im-chip-mark">
                {entry.label.charAt(0).toUpperCase()}
                {entry.logo ? (
                  <img
                    alt=""
                    height={22}
                    loading="lazy"
                    onError={(event) => {
                      event.currentTarget.style.display = "none";
                    }}
                    src={entry.logo}
                    width={22}
                  />
                ) : null}
              </span>
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <hr className="im-rule" />

      <div className="im-block">
        <Eyebrow id="im-file-label" n={2}>
          {t("import.statement_from", { platform: platform.label })}
        </Eyebrow>
        {/* The drop zone the Streamlit uploader draws, in this app's words: a
            bare <input type=file> prints "Choose File / No file chosen" in the
            browser's language rather than the reader's, and says nothing about
            what it takes. The input is still the control — visually hidden,
            focusable, inside the label that opens it — so the keyboard and a
            screen reader get the native dialog, and a drop lands on the same
            pipeline as a pick. */}
        <label
          className={dragging ? "im-drop im-drop-on" : "im-drop"}
          onDragEnter={(event) => {
            event.preventDefault();
            onDragging(true);
          }}
          onDragLeave={(event) => {
            // Leaving for a child of the zone is not leaving the zone.
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              onDragging(false);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <input
            accept={acceptOf(accepts)}
            aria-describedby="im-file-cap"
            aria-labelledby="im-file-label"
            className="im-file"
            id="im-file"
            key={platform.key}
            onChange={onPick}
            ref={file}
            type="file"
          />
          <span aria-hidden="true" className="im-drop-icon">
            <Glyph name={chosen ? "fileOk" : "file"} />
          </span>
          <span className="im-drop-text">
            <span className="im-drop-title">
              {dragging ? (
                t("import.drop_release")
              ) : chosen ? (
                <>
                  {chosen.filename}{" "}
                  <span className="im-drop-size">· {sizeLabel(chosen.bytes)}</span>
                </>
              ) : (
                t("import.drop_title")
              )}
            </span>
            <span className="im-drop-cap" id="im-file-cap">
              {chosen ? `${t("import.drop_replace")} · ${cap}` : cap}
            </span>
          </span>
          <span aria-hidden="true" className="im-btn im-btn-outline im-drop-btn">
            {t("import.drop_browse")}
          </span>
        </label>

        {errors.length > 0 && (
          <ul className="im-errors" role="alert">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        {hint && <p className="im-fine">{platform.hint}</p>}

        <div className="im-source-foot">
          {/* The second door into the same pipeline, for a reader whose browser
              will not hand over a file at all: a managed device can switch
              file dialogs off outright, and that reaches the app as "no file". */}
          <button
            aria-controls="im-paste-body"
            aria-expanded={pasting}
            className="im-disclose"
            onClick={() => setPasting((open) => !open)}
            type="button"
          >
            <Glyph name="right" />
            {t("import.paste_expander")}
          </button>
          {wipe}
          {/* Hidden rather than unmounted, so closing it keeps what was pasted. */}
          <div className="im-paste-body" hidden={!pasting} id="im-paste-body">
            <p className="im-fine">{t("import.paste_caption")}</p>
            <label className="im-label" htmlFor="im-paste">
              {t("import.paste_label", { platform: platform.label })}
            </label>
            {/* No button: a text area commits on blur, which is the same
                moment the Streamlit widget hands its value over. */}
            <textarea
              className="im-paste"
              id="im-paste"
              key={platform.key}
              onBlur={onPaste}
              placeholder={t("import.paste_placeholder")}
              rows={8}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * A file's size the way the uploader caption states the cap: whole kilobytes
 * under a megabyte, one decimal of megabytes above it. Units are symbols, the
 * same in every catalog, so there is nothing here to translate.
 */
function sizeLabel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
