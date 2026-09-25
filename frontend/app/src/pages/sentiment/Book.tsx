/**
 * The reader's own half, at length: what this regime does to what they hold.
 *
 * Fixed weights on purpose — this reads what the account owns NOW under the
 * current regime, not how it has performed. The Portfolio page owns that
 * question, and answering it twice in two places is how the two end up
 * disagreeing.
 */

import type { ReactNode } from "react";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { DownBody } from "./Down";
import { DriftPill } from "./Hero";
import { fixed, maybe, percent, sectorKey, share, signed } from "./format";
import { topSectors } from "./logic";
import type { PulseBook, TrendBlock, TrendRow } from "./types";

function Tile({
  label,
  value,
  note,
  pill,
}: {
  label: string;
  value: string;
  note: string;
  pill?: ReactNode;
}) {
  return (
    <div className="sn-bk-tile">
      <span className="sn-bk-l">{label}</span>
      <span className="sn-bk-v">{value}</span>
      {pill}
      <span className="sn-bk-n">{note}</span>
    </div>
  );
}

/**
 * The reader's own half needs the rotation block as well as its own endpoint:
 * `/pulse/book` sends the sector TILT against the benchmark, and the sentence
 * about which of their sectors is leading needs the sectors' own excess
 * returns, which ride on `/pulse/tables`. Absent until that query lands, which
 * is a sentence short rather than a wrong one.
 */
export function Book({
  book,
  rotation,
  onRetry,
}: {
  book: PulseBook;
  rotation: TrendBlock | null;
  onRetry?: () => void;
}) {
  const t = useT();
  const empty =
    book.beta === null &&
    book.usd_share === null &&
    Object.keys(book.currency_weights).length === 0;

  const head = (
    <div className="sn-sec-head">
      <h3 className="sn-sec-t" id="ag-book">
        {t("sentiment.book_title")}
      </h3>
      <span className="sn-badge">{t("sentiment.book_badge")}</span>
      <span className="sn-spacer" />
      <span className="sn-mono">{t("sentiment.book_src")}</span>
    </div>
  );

  // A replay that could not be priced is not an empty ledger, and the import
  // invitation below would say it is.
  if (empty && book.unavailable) {
    return (
      <>
        {head}
        <DownBody reason={book.unavailable} onRetry={onRetry} />
      </>
    );
  }

  if (empty) {
    // The hero's right half already carries the full invitation; repeating it
    // here would be the same empty state twice on one screen.
    return (
      <>
        {head}
        <span className="sn-help">{t("sentiment.book_empty")}</span>
        <Link page="import" className="sn-cta">
          {t("sentiment.book_import_cta")}
        </Link>
      </>
    );
  }

  const drag = book.fx_drag;
  const tilts = Object.entries(book.sector_tilt).sort((a, b) => b[1] - a[1]);
  const notes: string[] = [];
  if (book.bond_correlation !== null) {
    notes.push(
      t("sentiment.book_bond_corr", {
        value: fixed(book.bond_correlation, 2),
        prior: fixed(book.bond_correlation_then, 2),
      }),
    );
  }
  if (drag !== null) {
    notes.push(t("sentiment.fx_note", { value: percent(drag, 2) }));
  }
  if (book.rotation_capture !== null) {
    notes.push(
      t("sentiment.rotation_capture", { value: percent(book.rotation_capture, 2) }),
    );
  }
  // Which of their largest sectors is beating the index right now. The three
  // come off the book's own split and the month figure off the rotation block,
  // where it is already an excess return over the benchmark — so this reads a
  // sign rather than computing a comparison.
  const names = (rows: TrendRow[]) =>
    rows
      .map((row) => maybe(t, `sentiment.sector_${sectorKey(row.name)}`) ?? row.name)
      .join(", ");
  const { leading, lagging } = topSectors(rotation, book.sector_weights);
  if (leading.length > 0) {
    notes.push(t("sentiment.note_leading", { names: names(leading) }));
  }
  if (lagging.length > 0) {
    notes.push(t("sentiment.note_lagging", { names: names(lagging) }));
  }

  return (
    <>
      {head}
      <div className="sn-bk">
        <Tile
          label={t("sentiment.beta_equity")}
          value={fixed(book.beta, 2)}
          note={t("sentiment.beta_equity_help")}
          pill={<DriftPill now={book.beta_rolling} then={book.beta_rolling_then} />}
        />
        {/* Duration, credit and emerging markets: the same regression on the
            same EUR-rebased basket, one tile each. The pill is the drift of
            the rolling beta, as on the equity tile — the level alone cannot
            say the book got more rate-sensitive without anyone trading. */}
        {(book.betas ?? []).map((entry) => (
          <Tile
            key={entry.key}
            label={t(`sentiment.beta_${entry.key}`)}
            value={fixed(entry.beta, 2)}
            note={t(`sentiment.beta_${entry.key}_help`)}
            pill={<DriftPill now={entry.rolling} then={entry.rolling_then} />}
          />
        ))}
        <Tile
          label={t("sentiment.side_corr")}
          value={signed(book.bond_correlation, 2)}
          note={t("sentiment.stock_bond_corr_note")}
          pill={
            <DriftPill now={book.bond_correlation} then={book.bond_correlation_then} />
          }
        />
        <Tile
          label={t("sentiment.usd_share")}
          value={share(book.usd_share)}
          note={t("sentiment.usd_share_help")}
          pill={
            drag === null ? undefined : (
              <span className={`sn-pill ${drag >= 0 ? "sn-pill-up" : "sn-pill-down"}`}>
                {t("sentiment.fx_pill", { value: percent(drag, 2) })}
              </span>
            )
          }
        />
      </div>

      {tilts.length > 0 && (
        <div className="sn-tilt">
          <span className="sn-mono">{t("sentiment.col_tilt")}</span>
          <div className="sn-tilt-rows">
            {tilts.map(([name, weight]) => (
              <span className="sn-tilt-row" key={name}>
                <span>{maybe(t, `sentiment.sector_${sectorKey(name)}`) ?? name}</span>
                {/* Uncoloured: an active weight is a position, not a verdict —
                    an underweight in the sector that led is a cost and an
                    underweight in the one that fell is not. */}
                <b>{signed(weight * 100, 1, "pp")}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      {notes.length > 0 && (
        <div className="sn-notes">
          {notes.map((note) => (
            <span className="sn-note" key={note}>
              {note}
            </span>
          ))}
        </div>
      )}
      {/* The weights answered and the betas did not: the tiles already say
          "n/a", and this says why, with the same stamp as every other block
          on the page. */}
      {book.unavailable && <DownBody reason={book.unavailable} onRetry={onRetry} />}
      <p className="sn-caption">{t("sentiment.book_help")}</p>
    </>
  );
}
