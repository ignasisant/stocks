/**
 * Import: a broker statement becoming ledger rows.
 *
 * The flow this page has always had — pick a platform, upload, preview (which
 * writes nothing), read the tiers, commit — and the reason it is tiered is in
 * `web/app_pages/import_transactions.py`: a bad export must not be able to
 * corrupt a cost basis silently. So nothing here reports a count where it could
 * report the rows, and the commit's own answer is what gets shown afterwards,
 * not the preview's prediction of it.
 *
 * Beside the import sit two repairs, because a statement cannot carry what they
 * fix: splits the book never heard about (`Splits`, on request — it prices every
 * holding against Yahoo) and shares that only changed broker but read as a sale
 * (`Moves`, on every visit — it reads the ledger alone). Both propose; neither
 * writes until the reader names what they believe.
 *
 * The example statement is here for the same reason it is there: a reader with
 * nothing to import can still see the real thing happen, because its bytes go
 * through this very flow rather than through a route of their own.
 */

import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FocusEvent } from "react";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import type { Query } from "../../shell/useApi";
import {
  MAX_BYTES,
  asBase64,
  book,
  dismissRecord,
  lastImport,
  listPlatforms,
  preview as previewOf,
  undoLast,
} from "./api";
import type { Book, LastImport, Platform, Result, Staged } from "./api";
import { CommitPanel } from "./Commit";
import { Ledger } from "./Ledger";
import { Moves } from "./Moves";
import { Rich } from "./Rich";
import { Sample } from "./Sample";
import { Splits } from "./Splits";
import { RowTable } from "./Tables";
import { Tiers } from "./Tiers";
import { NO_WIPE, Wipe } from "./Wipe";
import type { WipeChoice } from "./Wipe";
import { pastedFile } from "./paste";
import { useVocabulary } from "./text";
import { SignInWall } from "../../shell/guest";
import { useGuest } from "../../shell/session";
import "./import.css";

export default function Page() {
  const t = useT();
  // In the rail and refusing inside, as Streamlit does and for the reason
  // given on Profile. A guest has no book to import into and the shared demo
  // one is not it, so `/v1/import/*` is shut to them at the API too — the wall
  // here is what makes that a sentence rather than a failed request.
  const guest = useGuest();
  const platforms = useApi(
    () => (guest ? Promise.resolve({ platforms: [] }) : listPlatforms()),
    [guest],
  );
  return (
    <div className="im-page">
      <h1 className="im-h1">{t("import.title")}</h1>
      <p className="im-lede">{t("import.intro_caption")}</p>
      {guest ? <SignInWall text="common.sign_in" /> : null}
      <Loaded query={platforms} skeleton={<Skeleton rows={6} />}>
        {(data) =>
          data.platforms.length > 0 ? <Importer platforms={data.platforms} /> : null
        }
      </Loaded>
    </div>
  );
}

function Importer({ platforms }: { platforms: Platform[] }) {
  const t = useT();
  const { params, setParams } = useRoute();
  const platform =
    platforms.find((entry) => entry.key === params.get("platform")) ?? platforms[0]!;

  const [staged, setStaged] = useState<Staged | null>(null);
  const [oversize, setOversize] = useState<number | null>(null);
  // A pasted format this platform has no parser for, by its extension.
  const [wrongType, setWrongType] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  // A file held over the drop zone, which lights it up as a target.
  const [dragging, setDragging] = useState(false);
  const [wipe, setWipe] = useState<WipeChoice>(NO_WIPE);
  // Bumped by anything that writes: the ledger count, the last-import record
  // and both repairs are stale the moment a commit, an undo or a wipe lands.
  const [writes, setWrites] = useState(0);
  const wrote = () => setWrites((n) => n + 1);

  const file = useRef<HTMLInputElement>(null);
  const pasted = useRef("");

  const ledger = useApi(() => book(), [writes]);
  const last = useApi(() => lastImport(), [writes]);
  // A statement must never be parsed by another platform's parser, so the
  // staged file is part of this query's identity and not just its input. The
  // wipe is too: with it set, validation runs against an empty ledger, and a
  // preview taken without it is a preview of a different import.
  const preview = useApi(
    async () => (staged ? await previewOf(platform.key, staged, wipe.on) : null),
    [platform.key, staged, wipe.on],
  );

  const held = ledger.state === "loaded" ? ledger.data : null;
  // What the repairs work on and what the example statement must not be offered
  // against. Demo rows are neither: they are deleted by the first real import,
  // and `_real_rows` leaves them out of both scans for the same reason.
  const real = held ? (held.complete ? held.total - held.demo : held.total) : 0;
  const nothingReal = held !== null && held.complete && real === 0;
  const noRecord = last.state === "loaded" && !last.data.filename;

  const stage = async (
    name: string,
    blob: Blob,
    surface: "import" | "paste" = "import",
  ) => {
    setResult(null);
    if (blob.size > MAX_BYTES) {
      // Said before the upload rather than after: the API answers 413 above
      // this, and a reader who waited for the round trip learns nothing extra.
      setOversize(blob.size);
      setStaged(null);
      return;
    }
    setOversize(null);
    setStaged({
      filename: name,
      content: await asBase64(blob),
      bytes: blob.size,
      surface,
    });
  };

  const onPick = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    if (picked) {
      setWrongType(null);
      void stage(picked.name, picked);
    }
  };

  // A dropped file skips the dialog, and with it the `accept` filter the
  // dialog applies — so the extension is checked here, and a format this
  // platform has no parser for is named the way a pasted one is.
  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (!dropped) return;
    const kind = dropped.name.includes(".")
      ? (dropped.name.split(".").pop() ?? "").toLowerCase()
      : "";
    if (!platform.file_types.includes(kind)) {
      setWrongType(kind || "?");
      setStaged(null);
      return;
    }
    setWrongType(null);
    void stage(dropped.name, dropped);
  };

  // No button: a text area commits on blur, which is the same moment the
  // Streamlit widget hands its value over.
  const onPaste = (event: FocusEvent<HTMLTextAreaElement>) => {
    const text = event.target.value.trim();
    if (!text || text === pasted.current) return;
    pasted.current = text;
    const asFile = pastedFile(text, platform.file_types);
    if ("wrong" in asFile) {
      // A base64 PDF pasted at a platform that reads only CSV: named here,
      // where it can be said in one sentence, rather than deep inside a parser
      // that would report it as an unreadable file.
      setWrongType(asFile.wrong);
      setStaged(null);
      return;
    }
    setWrongType(null);
    void stage(asFile.filename, asFile.blob, "paste");
  };

  const clear = () => {
    setStaged(null);
    setOversize(null);
    setWrongType(null);
    setResult(null);
    setWipe(NO_WIPE);
    pasted.current = "";
    if (file.current) file.current.value = "";
  };

  const choose = (key: string) => {
    if (key === platform.key) return;
    setParams({ platform: key });
    clear();
  };

  return (
    <>
      <Ledger
        book={ledger}
        onWiped={() => {
          // The book it was going to be validated against is gone, so the
          // preview on screen is about a ledger that no longer exists.
          clear();
          wrote();
        }}
      />

      {/* Both repairs before the importer, where the Streamlit page puts them:
          a book that is reporting a gain nobody made is worth fixing before
          another statement is poured on top of it. */}
      <Splits enabled={real > 0} onApplied={wrote} />
      <Moves enabled={real > 0} nonce={writes} onApplied={wrote} />

      <div className="im-field">
        <span className="im-label" id="im-platform">
          {t("import.importing_from")}
        </span>
        {/* One control at both sizes. Seven brand names do not fit a phone-width
            row side by side, which is why the Streamlit page falls back to a
            dropdown there; letting them wrap solves the same problem without a
            second control to keep in step. */}
        <div aria-labelledby="im-platform" className="im-platforms" role="group">
          {platforms.map((entry) => (
            <button
              aria-pressed={entry.key === platform.key}
              className={
                entry.key === platform.key
                  ? "im-platform im-platform-on"
                  : "im-platform"
              }
              key={entry.key}
              onClick={() => choose(entry.key)}
              type="button"
            >
              {/* The brand mark beside the name, as the Streamlit picker
                  draws it. Decorative — the name is the label — so an image
                  that fails to load simply goes away. */}
              {entry.logo ? (
                <img
                  alt=""
                  className="im-platform-logo"
                  height={16}
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                  src={entry.logo}
                  width={16}
                />
              ) : null}
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <div className="im-field">
        <span className="im-label" id="im-file-label">
          {t("import.uploader_label", {
            platform: platform.label,
            types: platform.file_types.map((kind) => kind.toUpperCase()).join(", "),
          })}
        </span>
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
            setDragging(true);
          }}
          onDragLeave={(event) => {
            // Leaving for a child of the zone is not leaving the zone.
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              setDragging(false);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <input
            accept={platform.file_types.map((kind) => `.${kind}`).join(",")}
            aria-describedby="im-file-cap"
            aria-labelledby="im-file-label"
            className="im-file"
            id="im-file"
            key={platform.key}
            onChange={onPick}
            ref={file}
            type="file"
          />
          <span className="im-drop-text">
            <span className="im-drop-title">
              {staged && staged.surface === "import"
                ? t("import.drop_chosen", {
                    name: staged.filename,
                    size: sizeLabel(staged.bytes),
                  })
                : t("import.drop_title")}
            </span>
            <span className="im-drop-cap" id="im-file-cap">
              {staged && staged.surface === "import"
                ? t("import.drop_replace")
                : t("import.drop_caption", {
                    cap: MAX_BYTES / (1024 * 1024),
                    types: platform.file_types
                      .map((kind) => kind.toUpperCase())
                      .join(", "),
                  })}
            </span>
          </span>
          <span className="im-drop-btn" aria-hidden="true">
            {t("import.drop_browse")}
          </span>
        </label>
      </div>

      {/* The second door into the same pipeline, for a reader whose browser
          will not hand over a file at all: a managed device can switch file
          dialogs off outright, and that reaches the app as "no file". */}
      <details className="im-details">
        <summary>{t("import.paste_expander")}</summary>
        <p className="im-help">{t("import.paste_caption")}</p>
        <label className="im-label" htmlFor="im-paste">
          {t("import.paste_label", { platform: platform.label })}
        </label>
        <textarea
          className="im-paste"
          id="im-paste"
          key={platform.key}
          onBlur={onPaste}
          placeholder={t("import.paste_placeholder")}
          rows={8}
        />
      </details>

      {oversize !== null && (
        <p className="im-bad">
          {t("import.file_too_large", {
            size: (oversize / (1024 * 1024)).toFixed(1),
            cap: MAX_BYTES / (1024 * 1024),
          })}
        </p>
      )}

      {wrongType !== null && (
        <p className="im-bad">
          {t("import.paste_wrong_type", {
            kind: wrongType.toUpperCase(),
            platform: platform.label,
            types: platform.file_types.map((kind) => kind.toUpperCase()).join(", "),
          })}
        </p>
      )}

      {staged && (
        <>
          {/* Before the preview and not beside the commit: the wipe decides
              what the validation is run against. */}
          <Wipe total={held?.total ?? 0} value={wipe} onChange={setWipe} />
          <Loaded query={preview} skeleton={<Skeleton rows={6} />}>
            {(outcome) =>
              outcome === null ? null : outcome.ok ? (
                <>
                  <Tiers preview={outcome.value} />
                  <CommitPanel
                    onCommitted={(committed) => {
                      setResult(committed);
                      setStaged(null);
                      setWipe(NO_WIPE);
                      pasted.current = "";
                      if (file.current) file.current.value = "";
                      wrote();
                    }}
                    platform={platform}
                    platforms={platforms}
                    preview={outcome.value}
                    staged={staged}
                    wipe={wipe}
                  />
                </>
              ) : (
                <p className="im-bad">
                  {t("import.no_rows_parsed", {
                    platform: platform.label,
                    hint: platform.hint,
                  })}
                </p>
              )
            }
          </Loaded>
        </>
      )}

      {result && <Committed ledger={ledger} result={result} />}

      {/* Also right after a commit: the batch that just landed is the one an
          undo would take back, and that offer belongs beside the receipt. */}
      {!staged && (
        <Loaded query={last} skeleton={<Skeleton rows={2} />}>
          {(record) =>
            record.filename ? (
              <LastBatch
                onDone={() => {
                  setResult(null);
                  wrote();
                }}
                platforms={platforms}
                record={record}
              />
            ) : null
          }
        </Loaded>
      )}

      {!staged && !result && (
        <>
          <p className="im-hint">{platform.hint}</p>
          {/* Only on the empty path, and only with nothing real to lose: this
              commits somebody else's trades, which is a tour in an empty book
              and a trap in a real one. */}
          {nothingReal && noRecord && (
            <Sample
              onPicked={(name, blob) => void stage(name, blob)}
              platform={platform}
            />
          )}
        </>
      )}
    </>
  );
}

/**
 * What the commit did — which is not what the preview predicted it would do.
 *
 * The commit re-parses and re-validates against a ledger that may have moved,
 * so it can refuse rows the preview accepted. Those are reported here rather
 * than dropped quietly.
 */
function Committed({ ledger, result }: { ledger: Query<Book>; result: Result }) {
  const t = useT();
  return (
    <section className="im-done">
      <Loaded query={ledger} skeleton={<Skeleton rows={1} />}>
        {(count) => (
          <p className="im-ok">
            {t("import.commit_success", { n: result.imported, total: count.total })}
          </p>
        )}
      </Loaded>
      {result.rejected.length > 0 && (
        <>
          <p className="im-bad">
            {t("import.rows_rejected", { n: result.rejected.length })}
          </p>
          <RowTable brief issues="errors" link={false} rows={result.rejected} />
        </>
      )}
      <p className="im-help">
        <Rich text={t("import.commit_help")} />
      </p>
    </section>
  );
}

/**
 * The last committed batch, and the two different things to do with it.
 *
 * Committed rows live in the ledger, so there is nothing to re-upload — *clear
 * last import* deletes the ids that commit inserted and no others, and
 * *dismiss* forgets the note while the rows stay exactly where they are. What
 * separates them is the ledger itself, which is why they are two buttons and
 * one caption rather than one button whose meaning has to be guessed.
 */
function LastBatch({
  onDone,
  platforms,
  record,
}: {
  onDone: () => void;
  platforms: Platform[];
  record: LastImport;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [busy, setBusy] = useState(false);
  const source = platforms.find((entry) => entry.key === record.platform);

  const act = async (call: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await call();
    } catch {
      // Nothing was deleted. Re-reading the record below is the honest
      // answer either way: it says what is still there.
    } finally {
      setBusy(false);
      onDone();
    }
  };

  return (
    <section className="im-last">
      <h2 className="im-h2">{t("import.last_import")}</h2>
      <p>
        <Rich
          text={
            t("import.last_import_summary", {
              filename: record.filename ?? "",
              platform: source?.label ?? record.platform ?? "",
              n: record.rows,
              when: record.imported_at ? vocab.when(record.imported_at) : "",
            }) + (record.wiped ? t("import.ledger_wiped_suffix") : "")
          }
        />
      </p>
      {/* What the commit wrote and what is left are two counts, and they part
          company as soon as a row is deleted by hand. The reader is told how
          many left rather than shown a batch that quietly shrank. */}
      {record.still_here < record.rows && (
        <p className="im-help">
          {t("import.rows_no_longer", { n: record.rows - record.still_here })}
        </p>
      )}
      {record.transactions.length > 0 && (
        <details className="im-details">
          <summary>{t("import.imported_rows_still", { n: record.still_here })}</summary>
          {/* A committed row has no parser issues left to report — it was
              accepted — so the table is handed the shape it expects with
              those two fields empty rather than being taught a second one. */}
          <RowTable
            rows={record.transactions.map((row) => ({
              ...row,
              issues: [],
              duplicate: false,
            }))}
          />
        </details>
      )}
      <div className="im-row">
        <button
          className="ag-btn"
          disabled={busy || record.still_here === 0}
          onClick={() => void act(undoLast)}
          type="button"
        >
          {t("import.clear_last_import", { n: record.still_here })}
        </button>
        <button
          className="ag-btn"
          disabled={busy}
          onClick={() => void act(dismissRecord)}
          type="button"
        >
          {t("import.dismiss_record")}
        </button>
      </div>
      <p className="im-help">
        <Rich text={t("import.last_import_help")} />
      </p>
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
