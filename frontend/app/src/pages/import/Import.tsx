/**
 * Import: a broker statement becoming ledger rows.
 *
 * The flow this page has always had — pick a platform, upload, preview (which
 * writes nothing), read the tiers, commit — is tiered because a bad export must
 * not be able to corrupt a cost basis silently. So nothing here reports a count
 * where it could report the rows, and the commit's own answer is what gets
 * shown afterwards, not the preview's prediction of it.
 *
 * The layout is the canvas's ("Aguait Importar Refactor", 1a–1c): the task in
 * the wide column, in the order it is done, and the book beside it in a rail —
 * what it holds now, the repairs it is waiting on, and the last batch with its
 * undo. The rail is read when it is needed and never pushes the task down;
 * when the page is too narrow for both it drops under the task and folds.
 *
 * The two repairs sit in that rail because a statement cannot carry what they
 * fix: splits the book never heard about (`Splits`, on request and once after
 * a commit — it prices every holding against Yahoo) and shares that only changed broker but read as
 * a sale (`Moves`, on every visit — it reads the ledger alone). Both propose;
 * neither writes until the reader names what they believe.
 *
 * The example statement is here for the same reason it is there: a reader with
 * nothing to import can still see the real thing happen, because its bytes go
 * through this very flow rather than through a route of their own.
 */

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FocusEvent } from "react";
import { Loaded, Refreshable, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { reportProblem } from "../../shell/report";
import { Link, useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Status } from "../../ui/Status";
import { TypeInstead } from "../../ui/TypeInstead";
import type { Query } from "../../shell/useApi";
import {
  MAX_BYTES,
  asBase64,
  book,
  lastImport,
  listPlatforms,
  nameOf,
  preview as previewOf,
  reportUnreadable,
  scanMoves,
} from "./api";
import type { Book, Platform, Preview, Result, Staged } from "./api";
import { Eyebrow, jump } from "./Card";
import { CommitPanel } from "./Commit";
import { Glyph } from "./Glyph";
import { Holdings } from "./Holdings";
import { LastBatch } from "./Last";
import { Ledger } from "./Ledger";
import { Repairs } from "./RepairCard";
import { Rich } from "./Rich";
import { Sample } from "./Sample";
import { Source } from "./Source";
import { STUCK_AFTER, missed } from "./stuck";
import { RowTable } from "./Tables";
import { Tiers } from "./Tiers";
import { NO_WIPE, Wipe } from "./Wipe";
import type { WipeChoice } from "./Wipe";
import { forget, keep, land, mark, preview as remembered, restored } from "./kept";
import { pastedFile } from "./paste";
import { platformHint, useVocabulary } from "./text";
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
  // In the rail and refusing inside, for the reason given on Profile. A guest
  // has no book to import into and the shared demo one is not it, so
  // `/v1/import/*` is shut to them at the API too — the wall here is what makes
  // that a sentence rather than a failed request.
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
  // What the page held when the reader followed one of its links away: back
  // here, the review they left rather than an empty drop zone (`kept`).
  const [left] = useState(restored);
  const platform =
    platforms.find(
      (entry) => entry.key === (params.get("platform") ?? left?.platform),
    ) ?? platforms[0]!;
  // The picked platform is only tried first: the model reads every file and
  // every parser checks it, so a Revolut PDF dropped under Trading 212 is read
  // anyway. An older server sends no list, and there the platform's is it.
  const kinds = accepts.length > 0 ? accepts : platform.file_types;

  const [staged, setStaged] = useState<Staged | null>(left?.staged ?? null);
  const [oversize, setOversize] = useState<number | null>(null);
  // A pasted or dropped format nothing here reads, by its extension.
  const [wrongType, setWrongType] = useState<string | null>(null);
  // A file the browser was handed and could not read.
  const [unreadable, setUnreadable] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [dragging, setDragging] = useState(false);
  const [wipe, setWipe] = useState<WipeChoice>(left?.wipe ?? NO_WIPE);
  // Bumped by anything that writes: the ledger count, the last-import record,
  // both repairs and the preview itself are stale the moment a commit, an
  // undo, a repair or a wipe lands.
  const [writes, setWrites] = useState(0);
  const wrote = () => {
    forget();
    setWrites((n) => n + 1);
  };
  // A move proposal the server no longer makes (409): ask again.
  const [again, setAgain] = useState(0);
  // Commits made here, and the splits the scan after each one found missing.
  const [commits, setCommits] = useState(0);
  const [gaps, setGaps] = useState(0);
  // Tries since the last commit that left nothing to commit (`stuck.ts`).
  const [misses, setMisses] = useState(0);
  const miss = () => setMisses((n) => n + 1);

  const file = useRef<HTMLInputElement>(null);
  const pasted = useRef("");
  const root = useRef<HTMLDivElement>(null);

  // Before the preview is asked, so the ask finds this statement kept.
  useEffect(() => keep(staged, wipe, platform.key), [staged, wipe, platform.key]);

  // A write re-reads both; the figures on screen stay up, dimmed, meanwhile.
  const ledger = useApi(() => book(), [writes], { keep: true });
  const last = useApi(() => lastImport(), [writes], { keep: true });
  // The platform is part of this query's identity and not just its input: it
  // is the parser tried first, and the one whose reading the model is checked
  // against. The wipe is too: with it set, validation runs against an empty ledger, and a
  // preview taken without it is a preview of a different import. And so is
  // every write — the rail can undo a batch or book a transfer while a preview
  // is on screen, and the preview is validated against the ledger it moved.
  const preview = useApi(
    async () =>
      staged
        ? await remembered(platform.key, staged, wipe.on, () =>
            previewOf(platform.key, staged, wipe.on),
          )
        : null,
    [platform.key, staged, wipe.on, writes],
  );
  useEffect(() => {
    if (preview.state === "loaded") land(root.current);
  }, [preview.state]);
  // One reading, one count: a rail write validates the same statement again
  // and is not another try, the same file under another platform is.
  const tried = useRef<{ platform: string; staged: Staged | null; data: unknown }>({
    platform: "",
    staged: null,
    data: null,
  });
  const outcome = preview.state === "loaded" ? preview.data : null;
  useEffect(() => {
    const seen = tried.current;
    if (!staged || outcome === null || outcome === seen.data) return;
    const same = seen.platform === platform.key && seen.staged === staged;
    tried.current = { platform: platform.key, staged, data: outcome };
    if (!same && missed(outcome)) miss();
  }, [outcome]);

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
      setUnreadable(false);
      setOversize(blob.size);
      setStaged(null);
      miss();
      return;
    }
    setOversize(null);
    setUnreadable(false);
    let content: string;
    try {
      content = await asBase64(blob);
    } catch (error) {
      // A phone can hand over a file it cannot open — one still in Drive, one
      // shared out of a chat app — and the read fails before anything is sent.
      // Said here, and reported, because otherwise nobody hears of it: not the
      // reader, who saw the zone do nothing, nor the server.
      setUnreadable(true);
      setStaged(null);
      // So picking the same file again, once it is saved locally, still fires.
      if (file.current) file.current.value = "";
      reportUnreadable(platform.key, name, blob, error);
      miss();
      return;
    }
    setStaged({ filename: name, content, bytes: blob.size, surface });
  };

  const onPick = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    if (picked) {
      setWrongType(null);
      void stage(nameOf(picked, kinds), picked);
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
      miss();
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
      miss();
      return;
    }
    setWrongType(null);
    void stage(asFile.filename, asFile.blob, "paste");
  };

  const clear = () => {
    setStaged(null);
    setOversize(null);
    setWrongType(null);
    setUnreadable(false);
    setResult(null);
    setWipe(NO_WIPE);
    pasted.current = "";
    if (file.current) file.current.value = "";
  };

  // The staged statement stays: the platform is only the parser tried first,
  // and the preview, keyed on it, reads the same file again under the new one.
  const choose = (key: string) => {
    if (key === platform.key) return;
    setParams({ platform: key });
    setResult(null);
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
  if (unreadable) errors.push(t("import.unreadable"));
  if (staged && preview.state === "loaded" && preview.data && !preview.data.ok)
    errors.push(
      t("import.nothing_read", {
        platform: platform.label,
        hint: platformHint(t, platform),
      }),
    );
  const stuck = misses >= STUCK_AFTER && !result;

  return (
    <div
      className="im-body"
      onClickCapture={(event) => mark(root.current, event.nativeEvent)}
      ref={root}
    >
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

        {/* Three tries and nothing booked: the fourth is not going to differ,
            so the page says so and offers the two ways that do not need the
            file to be read. Nothing is sent unless the reader writes it. */}
        {stuck && (
          <section
            aria-labelledby="im-stuck-title"
            aria-live="polite"
            className="im-card im-empty"
          >
            <h2 className="im-h3" id="im-stuck-title">
              {t("import.stuck_title")}
            </h2>
            <p className="im-fine">{t("import.stuck_caption")}</p>
            <div className="im-done-actions">
              <TypeInstead className="im-btn im-btn-primary" />
              <button
                className="im-btn im-btn-outline"
                onClick={() => reportProblem("bug")}
                type="button"
              >
                {t("import.stuck_report")}
              </button>
            </div>
          </section>
        )}

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
            {(outcome) => {
              if (outcome === null || !outcome.ok) return null;
              const read = outcome.value;
              const panel = (shown: Preview, keep: boolean) => (
                <CommitPanel
                  keep={keep}
                  onCommitted={(committed) => {
                    setResult(committed);
                    setStaged(null);
                    setWipe(NO_WIPE);
                    pasted.current = "";
                    if (file.current) file.current.value = "";
                    setMisses(0);
                    if (committed.imported > 0) setCommits((n) => n + 1);
                    wrote();
                  }}
                  platforms={platforms}
                  preview={shown}
                  staged={staged}
                  wipe={wipe}
                />
              );
              // A holdings report has no dated rows: its lines are dated here
              // first, and become the rows the same commit writes.
              return read.kind === "positions" && (read.holdings ?? []).length > 0 ? (
                <Holdings key={read.digest} preview={read}>
                  {(dated) => panel(dated, false)}
                </Holdings>
              ) : (
                <Tiers
                  // A new reading starts with its duplicates left out again,
                  // and with no ticker corrected.
                  key={`${read.digest}:${read.platform}`}
                  onVenue={wrote}
                  picked={platform}
                  preview={read}
                >
                  {(keep, shown) => panel(shown, keep)}
                </Tiers>
              );
            }}
          </Loaded>
        )}

        {result && (
          <Committed gaps={gaps} ledger={ledger} onAgain={clear} result={result} />
        )}

        {/* Only on the empty path, and only with nothing real to lose: the
            example commits somebody else's trades, which is a tour in an
            empty book and a trap in a real one. */}
        {empty && (
          <Sample
            onPicked={(name, blob) => void stage(name, blob)}
            platform={platform}
          />
        )}

        {/* No importer for this broker: tell the chat the trades instead. Shown
            while the book holds nothing real (empty or demo), never mid-review. */}
        {!staged && !result && nothingReal && !stuck && (
          <section aria-label={t("import.type_title")} className="im-card im-empty">
            <p className="im-fine">{t("import.type_caption")}</p>
            <TypeInstead className="im-btn im-btn-outline" />
          </section>
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
            commits={commits}
            moves={moves}
            nonce={writes}
            onApplied={wrote}
            onGaps={setGaps}
            onStale={() => setAgain((count) => count + 1)}
          />
        )}
        <Loaded query={last} skeleton={<Skeleton rows={2} />}>
          {(batch) =>
            batch.filename ? (
              <Refreshable>
                <LastBatch
                  onDone={() => {
                    setResult(null);
                    wrote();
                  }}
                  platforms={platforms}
                  record={batch}
                />
              </Refreshable>
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
  gaps,
  ledger,
  result,
  onAgain,
}: {
  /** Splits the scan after this commit found missing from the book. */
  gaps: number;
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
              <Refreshable>
                <p>
                  <Rich
                    text={t("import.done_sentence", {
                      n: vocab.num(result.imported, 0),
                      total: vocab.num(count.total, 0),
                    })}
                  />
                </p>
              </Refreshable>
            )}
          </Loaded>
          <p className="im-fine">
            {t("import.done_rejected", { n: vocab.num(result.rejected.length, 0) })}
          </p>
          {(result.duplicates ?? 0) > 0 && (
            <p className="im-fine">
              {vocab.tn("import.done_duplicates", result.duplicates ?? 0)}
            </p>
          )}
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
      {/* Said in the commit's own card: shares bought before a split read as
          a vast loss, and that must not be the first thing the book shows. */}
      {gaps > 0 && (
        <button
          className="im-done-fix"
          onClick={() => jump("im-repairs")}
          type="button"
        >
          <Glyph name="info" />
          <span>{vocab.tn("import.splits_banner", gaps)}</span>
          <Glyph name="right" />
        </button>
      )}
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
