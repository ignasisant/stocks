/**
 * Step one: the statement, and nothing else asked first.
 *
 * No broker to pick: every parser and the model check the file, so it says
 * whose it is (`ReadAs` shows the reading and lets the reader overrule it).
 * Brokers appear only folded under "where do I get my statement", as a help
 * for a reader who has none yet. Under the drop zone, the other ways in
 * (the paste box for a browser that will not hand over a file, the assistant
 * for a statement no parser here reads), then apart from them the wipe, which
 * has to be decided before the preview is read, not after.
 *
 * The handlers are the page's (`Import.tsx`), because the staged file is the
 * preview's identity; this only draws them.
 */

import { useState } from "react";
import type { ChangeEvent, DragEvent, FocusEvent, ReactNode, RefObject } from "react";
import { useT } from "../../shell/i18n";
import { MAX_BYTES, acceptOf } from "./api";
import { note } from "./api";
import type { Platform, Staged } from "./api";
import { Eyebrow } from "./Card";
import { Glyph } from "./Glyph";
import { platformHint } from "./text";
import { Way } from "./Way";

export function Source({
  platforms,
  accepts,
  staged,
  dragging,
  onDragging,
  onPick,
  onDrop,
  onPaste,
  file,
  errors,
  wipe,
  assistant,
}: {
  platforms: Platform[];
  /** Every extension a statement can arrive as. */
  accepts: string[];
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
  /** The wipe's tick and, once ticked, its confirmation. */
  wipe: ReactNode;
  /** The same statement, read in the assistant instead (`ToAssistant`). */
  assistant?: ReactNode;
}) {
  const t = useT();
  const [pasting, setPasting] = useState(false);
  const types = accepts.map((kind) => kind.toUpperCase()).join(", ");
  const cap = t("import.drop_caption", { cap: MAX_BYTES / (1024 * 1024), types });
  // A pasted statement has no file name to show, and the zone keeps offering a
  // file for it: the paste box below is where that text lives.
  const chosen = staged && staged.surface !== "paste" ? staged : null;

  return (
    <section aria-labelledby="im-file-label" className="im-card im-source">
      <div className="im-block">
        <Eyebrow id="im-file-label" n={1}>
          {t("import.step_statement")}
        </Eyebrow>
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
                <span className="im-drop-dnd">{t("import.drop_title")}</span>
              )}
            </span>
            <span className="im-drop-cap" id="im-file-cap">
              {chosen ? `${t("import.drop_replace")} · ${cap}` : cap}
            </span>
          </span>
          <span aria-hidden="true" className="im-btn im-btn-outline im-drop-btn">
            <span className="im-drop-browse">{t("import.drop_browse")}</span>
            <span className="im-drop-pick">{t("import.drop_pick")}</span>
          </span>
        </label>

        {errors.length > 0 && (
          <ul className="im-errors" role="alert">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        {!chosen && <Guide platforms={platforms} />}

        <p className="im-eyebrow im-ways-label" id="im-ways-label">
          {t("import.ways")}
        </p>
        <div aria-labelledby="im-ways-label" className="im-ways" role="group">
          {/* The second door into the same pipeline, for a reader whose browser
              will not hand over a file at all: a managed device can switch
              file dialogs off outright, and that reaches the app as "no file". */}
          <Way
            aria-controls="im-paste-body"
            aria-expanded={pasting}
            icon="paste"
            onClick={() => {
              if (!pasting) note("paste");
              setPasting((open) => !open);
            }}
            sub={t("import.paste_sub")}
            title={t("import.paste_expander")}
            trail="down"
          />
          {assistant}
          {/* Hidden rather than unmounted, so closing it keeps what was pasted.
              Below both tiles on a wide card, right under its own on a narrow
              one (the CSS orders it). */}
          <div className="im-paste-body" hidden={!pasting} id="im-paste-body">
            <p className="im-fine">{t("import.paste_caption")}</p>
            <label className="im-label" htmlFor="im-paste">
              {t("import.paste_label_any")}
            </label>
            {/* No button: the text area commits on blur. */}
            <textarea
              className="im-paste"
              id="im-paste"
              onBlur={onPaste}
              placeholder={t("import.paste_placeholder")}
              rows={8}
            />
          </div>
        </div>
        {wipe}
      </div>
    </section>
  );
}

/**
 * Where to get a statement, folded: broker chips and numbered steps for the
 * reader who has no file yet. Choosing a chip only changes the steps shown —
 * it never touches how the file is read.
 */
function Guide({ platforms }: { platforms: Platform[] }) {
  const t = useT();
  const [shown, setShown] = useState<string | null>(null);
  const entry = platforms.find((e) => e.key === shown) ?? null;
  const key = entry ? `import.guide_${entry.key}` : "";
  return (
    <details
      className="im-where"
      onToggle={(event) => {
        if (event.currentTarget.open) note("guide");
      }}
    >
      <summary>{t("import.where_title")}</summary>
      <div aria-label={t("import.where_title")} className="im-chips" role="group">
        {platforms.map((p) => (
          <button
            aria-pressed={p.key === shown}
            className={p.key === shown ? "im-chip im-chip-on" : "im-chip"}
            key={p.key}
            onClick={() => {
              if (p.key !== shown) note("guide_broker", p.key);
              setShown(p.key === shown ? null : p.key);
            }}
            type="button"
          >
            <span aria-hidden="true" className="im-chip-mark">
              {p.label.charAt(0).toUpperCase()}
              {p.logo ? (
                <img
                  alt=""
                  height={22}
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                  src={p.logo}
                  width={22}
                />
              ) : null}
            </span>
            {p.label}
          </button>
        ))}
      </div>
      {entry &&
        (t.has(key) ? (
          <div className="im-guide">
            <p className="im-guide-title">
              {t("import.guide_title", { platform: entry.label })}
            </p>
            <ol className="im-guide-steps">
              {t(key)
                .split("|")
                .map((step) => (
                  <li key={step}>{step}</li>
                ))}
            </ol>
          </div>
        ) : (
          <p className="im-fine">{platformHint(t, entry)}</p>
        ))}
      <p className="im-fine">{t("import.where_other")}</p>
    </details>
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
