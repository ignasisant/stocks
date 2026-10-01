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
 * The layout is the canvas's ("Aguait Importar Refactor", 1a–1c): the task in
 * the wide column, in the order it is done, and the book beside it in a rail —
 * what it holds now, the repairs it is waiting on, and the last batch with its
 * undo. The rail is read when it is needed and never pushes the task down;
 * when the page is too narrow for both it drops under the task and folds.
 *
 * The two repairs sit in that rail because a statement cannot carry what they
 * fix: splits the book never heard about (`Splits`, on request — it prices
 * every holding against Yahoo) and shares that only changed broker but read as
 * a sale (`Moves`, on every visit — it reads the ledger alone). Both propose;
 * neither writes until the reader names what they believe.
 *
 * The example statement is here for the same reason it is there: a reader with
 * nothing to import can still see the real thing happen, because its bytes go
 * through this very flow rather than through a route of their own.
 */

import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FocusEvent } from "react";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link, useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Status } from "../../ui/Status";
import type { Query } from "../../shell/useApi";
import {
  MAX_BYTES,
  asBase64,
  book,
  lastImport,
  listPlatforms,
  preview as previewOf,
  scanMoves,
} from "./api";
import type { Book, Platform, Result, Staged } from "./api";
import { Eyebrow, jump } from "./Card";
import { CommitPanel } from "./Commit";
import { Glyph } from "./Glyph";
import { LastBatch } from "./Last";
import { Ledger } from "./Ledger";
import { Repairs } from "./RepairCard";
import { Rich } from "./Rich";
import { Sample } from "./Sample";
import { Source } from "./Source";
import { RowTable } from "./Tables";
import { Tiers } from "./Tiers";
import { NO_WIPE, Wipe } from "./Wipe";
import type { WipeChoice } from "./Wipe";
import { pastedFile } from "./paste";
import { useVocabulary } from "./text";
import { SignInWall } from "../../shell/guest";
import { useGuest } from "../../shell/session";
import "./import.css";

/** The four steps the canvas numbers, in the order the page is worked. */
const STEPS = [
  "import.step_platform",
  "import.step_statement",
  "import.step_review",
  "import.step_confirm",
];

export default function Page() {
  // In the rail and refusing inside, as Streamlit does and for the reason
  // given on Profile. A guest has no book to import into and the shared demo
  // one is not it, so `/v1/import/*` is shut to them at the API too — the wall
  // here is what makes that a sentence rather than a failed request.
  const guest = useGuest();
  const platforms = useApi(
    () => (guest ? Promise.resolve({ platforms: [] }) : listPlatforms()),
    [guest],
  );
  if (guest) {
    return (
      <div className="im-page">
        <Head />
        <SignInWall text="import.guest" />
      </div>
    );
  }
  return (
    <div className="im-page">
      <Loaded
        query={platforms}
        skeleton={
          <>
            <Head />
            <Skeleton rows={6} />
          </>
        }
      >
        {(data) =>
          data.platforms.length > 0 ? (
            <Importer accepts={data.accepts ?? []} platforms={data.platforms} />
          ) : (
            <Head />
          )
        }
      </Loaded>
    </div>
  );
}

/**
 * The title, the one promise the page makes, and where the reader is in it.
 * `at` is the step being worked; five means all four are done.
 */
function Head({ at }: { at?: number }) {
  const t = useT();
  const current = at === undefined ? null : Math.min(at, STEPS.length);
  return (
    <header className="im-head">
      <h1 className="im-h1">{t("import.title")}</h1>
      <p className="im-lede">
        <Rich text={t("import.lede")} />
      </p>
      {at !== undefined && current !== null && (
        <>
          <ol aria-label={t("import.steps_label")} className="im-steps">
            {STEPS.map((key, index) => {
              const n = index + 1;
              const state = n < at ? "done" : n === at ? "cur" : "next";
              return (
                <li
                  aria-current={state === "cur" ? "step" : undefined}
                  className={`im-step im-step-${state}`}
                  key={key}
                >
                  <span aria-hidden="true" className="im-step-n">
                    {state === "done" ? "✓" : n}
                  </span>
                  {t(key)}
                </li>
              );
            })}
          </ol>
          {/* A phone has no row for four pills: the one being worked, counted.
              Hidden from assistive tech, which already has the list above. */}
          <p aria-hidden="true" className="im-steps-short">
            {t("import.step_of", {
              n: current,
              total: STEPS.length,
              label: t(STEPS[current - 1]!),
            })}
          </p>
        </>
      )}
    </header>
  );
}

function Importer({
  platforms,
  accepts,
}: {
  platforms: Platform[];
  /** Every extension the server reads, whichever platform is picked. */
  accepts: string[];
}) {
  const t = useT();
  const vocab = useVocabulary();
  const { params, setParams } = useRoute();
  const platform =
    platforms.find((entry) => entry.key === params.get("platform")) ?? platforms[0]!;
  // The picked platform is only tried first: the model reads every file and
  // every parser checks it, so a Revolut PDF dropped under Trading 212 is read
  // anyway. An older server sends no list, and there the platform's is it.
  const kinds = accepts.length > 0 ? accepts : platform.file_types;

  const [staged, setStaged] = useState<Staged | null>(null);
  const [oversize, setOversize] = useState<number | null>(null);
  // A pasted or dropped format nothing here reads, by its extension.
  const [wrongType, setWrongType] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [dragging, setDragging] = useState(false);
  const [wipe, setWipe] = useState<WipeChoice>(NO_WIPE);
  // Bumped by anything that writes: the ledger count, the last-import record,
  // both repairs and the preview itself are stale the moment a commit, an
  // undo, a repair or a wipe lands.
  const [writes, setWrites] = useState(0);
  const wrote = () => setWrites((n) => n + 1);
  // A move proposal the server no longer makes (409): ask again.
  const [again, setAgain] = useState(0);

  const file = useRef<HTMLInputElement>(null);
  const pasted = useRef("");

  const ledger = useApi(() => book(), [writes]);
  const last = useApi(() => lastImport(), [writes]);
  // The platform is part of this query's identity and not just its input: it
  // is the parser tried first, and the one whose reading the model is checked
  // against. The wipe is too: with it set, validation runs against an empty ledger, and a
  // preview taken without it is a preview of a different import. And so is
  // every write — the rail can undo a batch or book a transfer while a preview
  // is on screen, and the preview is validated against the ledger it moved.
  const preview = useApi(
    async () => (staged ? await previewOf(platform.key, staged, wipe.on) : null),
    [platform.key, staged, wipe.on, writes],
  );

  const held = ledger.state === "loaded" ? ledger.data : null;
  // What the repairs work on and what the example statement must not be offered
  // against. Demo rows are neither: they are deleted by the first real import,
  // and `_real_rows` leaves them out of both scans for the same reason.
  const real = held ? (held.complete ? held.total - held.demo : held.total) : 0;
  const nothingReal = held !== null && held.complete && real === 0;
  const record = last.state === "loaded" ? last.data : null;
  const hasLast = !!record?.filename;
  const empty = !staged && !result && nothingReal && record !== null && !hasLast;

  // Asked here rather than inside the rail card, because the phone banner at
  // the top of the task needs the same count.
  const moveScan = useApi(
    async () => (real > 0 ? await scanMoves() : { moves: [] }),
    [real > 0, writes, again],
  );
  const moves = moveScan.state === "loaded" ? moveScan.data.moves : [];

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
  // dialog applies — so the extension is checked here, and a format nothing
  // here reads is named the way a pasted one is.
  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (!dropped) return;
    const kind = dropped.name.includes(".")
      ? (dropped.name.split(".").pop() ?? "").toLowerCase()
      : "";
    if (!kinds.includes(kind)) {
      setWrongType(kind || "?");
      setStaged(null);
      return;
    }
    setWrongType(null);
    void stage(dropped.name, dropped);
  };

  const onPaste = (event: FocusEvent<HTMLTextAreaElement>) => {
    const text = event.target.value.trim();
    if (!text || text === pasted.current) return;
    pasted.current = text;
    const asFile = pastedFile(text, kinds);
    if ("wrong" in asFile) {
      // A base64 format nothing here reads: named here, where it can be said
      // in one sentence, rather than deep inside a reader that would report it
      // as an unreadable file.
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

  // Everything that stopped the statement being read, as the zone's own
  // lines: what went wrong, and what to do about it.
  const types = kinds.map((kind) => kind.toUpperCase()).join(", ");
  const errors: string[] = [];
  if (oversize !== null)
    errors.push(
      t("import.file_too_large", {
        size: (oversize / (1024 * 1024)).toFixed(1),
        cap: MAX_BYTES / (1024 * 1024),
      }),
    );
  if (wrongType !== null)
    errors.push(t("import.wrong_type", { kind: wrongType.toUpperCase(), types }));
  if (staged && preview.state === "loaded" && preview.data && !preview.data.ok)
    errors.push(
      t("import.nothing_read", { platform: platform.label, hint: platform.hint }),
    );

  return (
    <div className="im-body">
      <div className="im-main">
        <Head at={result ? 5 : staged ? 3 : 2} />

        {/* Beside the task the repairs card says this itself; under it, the
            card is a screen away, so the one line that matters comes up here. */}
        {moves.length > 0 && (
          <button
            className="im-banner"
            onClick={() => jump("im-repairs")}
            type="button"
          >
            <Glyph name="info" />
            <span>{vocab.tn("import.repairs_banner", moves.length)}</span>
            <Glyph name="right" />
          </button>
        )}

        <Source
          dragging={dragging}
          errors={errors}
          file={file}
          hint={!staged && !empty}
          onChoose={choose}
          onDragging={setDragging}
          onDrop={onDrop}
          onPaste={onPaste}
          onPick={onPick}
          accepts={kinds}
          platform={platform}
          platforms={platforms}
          staged={staged}
          // Before the preview and not beside the commit: the wipe decides
          // what the validation is run against.
          wipe={
            <Wipe
              hasLast={hasLast}
              onChange={setWipe}
              total={held?.total ?? 0}
              value={wipe}
            />
          }
        />

        {staged && (
          <Loaded
            query={preview}
            skeleton={
              <div className="im-card">
                <Status label={t("import.work_reading")} />
                <Skeleton rows={6} />
              </div>
            }
          >
            {(outcome) =>
              outcome !== null && outcome.ok ? (
                <Tiers picked={platform} preview={outcome.value}>
                  <CommitPanel
                    onCommitted={(committed) => {
                      setResult(committed);
                      setStaged(null);
                      setWipe(NO_WIPE);
                      pasted.current = "";
                      if (file.current) file.current.value = "";
                      wrote();
                    }}
                    platforms={platforms}
                    preview={outcome.value}
                    staged={staged}
                    wipe={wipe}
                  />
                </Tiers>
              ) : null
            }
          </Loaded>
        )}

        {result && <Committed ledger={ledger} onAgain={clear} result={result} />}

        {/* Only on the empty path, and only with nothing real to lose: the
            example commits somebody else's trades, which is a tour in an
            empty book and a trap in a real one. */}
        {empty && (
          <Sample
            onPicked={(name, blob) => void stage(name, blob)}
            platform={platform}
          />
        )}
      </div>

      <aside aria-label={t("import.book_now")} className="im-rail">
        <Ledger
          book={ledger}
          hasLast={hasLast}
          nonce={writes}
          onWiped={() => {
            // The book it was going to be validated against is gone, so the
            // preview on screen is about a ledger that no longer exists.
            clear();
            wrote();
          }}
        />
        {real > 0 && (
          <Repairs
            moves={moves}
            onApplied={wrote}
            onStale={() => setAgain((count) => count + 1)}
          />
        )}
        <Loaded query={last} skeleton={<Skeleton rows={2} />}>
          {(batch) =>
            batch.filename ? (
              <LastBatch
                onDone={() => {
                  setResult(null);
                  wrote();
                }}
                platforms={platforms}
                record={batch}
              />
            ) : null
          }
        </Loaded>
      </aside>
    </div>
  );
}

/**
 * What the commit did — which is not what the preview predicted it would do.
 *
 * The commit validates the previewed rows again against a ledger that may have
 * moved, so it can refuse rows the preview accepted. Those are reported here rather
 * than dropped quietly, and their count is said even when it is zero.
 */
function Committed({
  ledger,
  result,
  onAgain,
}: {
  ledger: Query<Book>;
  result: Result;
  onAgain: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  return (
    <section aria-live="polite" className="im-card im-done">
      <div className="im-done-main">
        <span aria-hidden="true" className="im-done-mark">
          <Glyph name="check" />
        </span>
        <div className="im-done-text">
          <Eyebrow n={4}>{t("import.confirm")}</Eyebrow>
          <Loaded query={ledger} skeleton={<Skeleton rows={1} />}>
            {(count) => (
              <p>
                <Rich
                  text={t("import.done_sentence", {
                    n: vocab.num(result.imported, 0),
                    total: vocab.num(count.total, 0),
                  })}
                />
              </p>
            )}
          </Loaded>
          <p className="im-fine">
            {t("import.done_rejected", { n: vocab.num(result.rejected.length, 0) })}
          </p>
        </div>
        <div className="im-done-actions">
          <Link className="im-btn im-btn-primary" page="portfolio">
            {t("import.go_to", { page: t("nav.portfolio") })}
          </Link>
          <Link className="im-btn im-btn-outline" page="home">
            {t("import.go_to", { page: t("nav.home") })}
          </Link>
          <button className="im-btn im-btn-text" onClick={onAgain} type="button">
            {t("import.import_another")}
          </button>
        </div>
      </div>
      {result.rejected.length > 0 && (
        <RowTable
          brief
          issues="errors"
          link={false}
          rows={result.rejected}
          tone="bad"
        />
      )}
    </section>
  );
}
