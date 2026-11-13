/**
 * The read in one look: how the book and the outside names split by verdict,
 * and a chip per verdict to pick some out.
 *
 * Each side is one stacked bar, a segment per verdict in reading order and in
 * its tone, so "mostly holds, two to sell" is seen before a number is read.
 * The chips under it carry the counts; pressing one lights its names on the
 * map and narrows both tables to them. The pick rides `?v=` and cuts nothing
 * else: the plan and the question for the assistant are about the whole read.
 */

import { useLang, useT } from "../../shell/i18n";
import { verdictTone } from "./format";
import type { ReviewRow, Verdict } from "./types";
import { verdictCounts } from "./verdicts";

export function VerdictBar({
  held,
  candidates,
  picked,
  onPick,
}: {
  held: ReviewRow[];
  candidates: ReviewRow[];
  picked: Verdict[];
  onPick: (next: Verdict[]) => void;
}) {
  const t = useT();
  const counts = verdictCounts([...held, ...candidates]);
  if (counts.length < 2) return null;
  const on = new Set(picked);
  const toggle = (verdict: Verdict) =>
    onPick(
      on.has(verdict) ? picked.filter((one) => one !== verdict) : [...picked, verdict],
    );
  return (
    <section className="ag-rev-card ag-rev-vbar" aria-label={t("review.vbar_label")}>
      <div className="ag-rev-vbar-bars">
        <Stack label={t("review.vbar_held")} rows={held} picked={on} />
        <Stack label={t("review.vbar_outside")} rows={candidates} picked={on} />
      </div>
      <div
        className="ag-rev-vbar-chips"
        role="group"
        aria-label={t("review.vbar_label")}
      >
        {counts.map(({ verdict, count }) => (
          <button
            key={verdict}
            type="button"
            className="ag-rev-vbar-chip"
            aria-pressed={on.has(verdict)}
            onClick={() => toggle(verdict)}
          >
            <span
              className={`ag-rev-vbar-dot ag-rev-vbar-${verdictTone(verdict)}`}
              aria-hidden="true"
            />
            {t(`review.verdict_${verdict}`)}
            <span className="ag-rev-vbar-n">{count}</span>
          </button>
        ))}
        {picked.length > 0 ? (
          <button
            type="button"
            className="ag-rev-vbar-chip ag-rev-vbar-clear"
            onClick={() => onPick([])}
          >
            {t("review.vbar_all")}
          </button>
        ) : null}
      </div>
    </section>
  );
}

/** One side's split, a segment per verdict; the picked ones stay solid. */
function Stack({
  label,
  rows,
  picked,
}: {
  label: string;
  rows: ReviewRow[];
  picked: Set<Verdict>;
}) {
  const t = useT();
  const lang = useLang();
  if (rows.length === 0) return null;
  const counts = verdictCounts(rows);
  const words = new Intl.ListFormat(lang, { type: "unit", style: "narrow" }).format(
    counts.map(({ verdict, count }) => `${t(`review.verdict_${verdict}`)} ${count}`),
  );
  return (
    <div className="ag-rev-vbar-row">
      <span className="ag-rev-vbar-label">
        {label} <span className="ag-rev-vbar-n">{rows.length}</span>
      </span>
      <span className="ag-rev-vbar-track" role="img" aria-label={`${label}: ${words}`}>
        {counts.map(({ verdict, count }) => (
          <span
            key={verdict}
            className={`ag-rev-vbar-seg ag-rev-vbar-${verdictTone(verdict)}`}
            data-dim={picked.size > 0 && !picked.has(verdict) ? "" : undefined}
            style={{ flexGrow: count }}
            title={`${t(`review.verdict_${verdict}`)} · ${count}`}
          />
        ))}
      </span>
    </div>
  );
}
