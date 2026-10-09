/**
 * The question Review hands the assistant, written from the rows on screen.
 *
 * The assistant starts from the page's read rather than re-deriving one: each
 * name with its verdict, weight and target, the money and tax of the move,
 * both scores, the reasons in words and the few figures the scores leaned on.
 * It is built from the filtered rows, so a reader looking at one sector asks
 * about that sector. It goes into the composer unsent (`draftAssistant`): the
 * reader sees what is asked and can cut or add to it.
 *
 * The chat refuses a message over 4,000 characters (`routes/chat.py`
 * `MAX_MESSAGE`), so rows are added in the page's own order — actions first —
 * until the budget is spent, and the rest are counted, not dropped silently.
 */

import { maybe, sectorKey } from "../sentiment/format";
import { OWN_LABEL, metric, money, percent, score } from "./format";
import type { Review, ReviewRow } from "./types";

type T = (key: string, slots?: Record<string, string | number>) => string;

/** Under `MAX_MESSAGE` with room for a line the reader adds. */
export const BUDGET = 3800;

/** The figures a line carries, the first three a row has. */
const FIGURES = ["pe_fwd", "owner_fcf_yield", "fcf_yield", "roic", "revenue_growth"];

function line(row: ReviewRow, data: Review, t: T, lang: string): string {
  const name = row.symbol || row.ticker;
  const sector = row.sector
    ? (maybe(t, `sentiment.sector_${sectorKey(row.sector)}`) ?? row.sector)
    : null;
  const head = sector ? `${name} (${sector})` : name;
  const parts: string[] = [t(`review.verdict_${row.verdict}`)];
  if (row.held) {
    const weight = percent(row.weight, lang);
    const target = percent(row.target_weight, lang);
    if (weight)
      parts[0] +=
        target && target !== weight ? `, ${weight} → ${target}` : `, ${weight}`;
    const move = money(row.delta, data.base, lang, true);
    const tax = money(row.tax, data.plan.tax_currency, lang);
    if (move)
      parts[0] += tax ? ` (${move}, ${t("review.col_tax")} ${tax})` : ` (${move})`;
    const pnl = percent(row.pnl_pct, lang);
    if (pnl) parts.push(`${t("review.col_pnl")} ${pnl}`);
  }
  if (row.quality !== null && row.cheapness !== null) {
    parts.push(
      t("review.prompt_scores", {
        quality: score(row.quality) ?? "",
        cheapness: score(row.cheapness) ?? "",
      }),
    );
  }
  const reasons = row.reasons.slice(0, 3).map((code) => t(`review.reason_${code}`));
  if (reasons.length) parts.push(reasons.join("; "));
  const figures: string[] = [];
  for (const key of FIGURES) {
    if (figures.length === 3) break;
    // Owner FCF already says what plain FCF would; one of the two.
    if (key === "fcf_yield" && row.metrics.owner_fcf_yield != null) continue;
    const value = metric(key, row.metrics[key], lang);
    if (!value) continue;
    const label = t(OWN_LABEL.has(key) ? `review.metric_${key}` : `kpi.${key}.label`);
    figures.push(`${label} ${value}`);
  }
  if (figures.length) parts.push(figures.join(", "));
  if (!row.held && row.buy_after)
    parts.push(t("review.buy_after", { date: row.buy_after }));
  return `- ${head}: ${parts.join(" · ")}`;
}

/**
 * The prompt. `filter` is the filter already in words ("Technology · 5–10%"),
 * empty when nothing is filtered.
 */
export function buildPrompt(data: Review, t: T, lang: string, filter = ""): string {
  const head = [t("review.prompt_intro", { date: data.as_of, base: data.base })];
  if (filter) head.push(t("review.prompt_filter", { filter }));
  if (data.held.length) {
    head.push(
      t("review.prompt_plan", {
        sells: money(data.plan.sells, data.base, lang) ?? "—",
        buys: money(data.plan.buys, data.base, lang) ?? "—",
        tax: money(data.plan.tax, data.plan.tax_currency, lang) ?? t("review.na"),
      }),
    );
  }
  const tail = t("review.prompt_ask");

  const sections: { title: string; rows: ReviewRow[] }[] = [
    { title: t("review.prompt_held"), rows: data.held },
    { title: t("review.prompt_outside"), rows: data.candidates },
  ].filter((section) => section.rows.length > 0);

  const lines: string[] = [];
  // Room for the "and N more" line, whatever N turns out to be.
  const reserve = t("review.prompt_more", { count: 999 }).length + 2;
  let used = head.join("\n").length + tail.length + 4 + reserve;
  let left = 0;
  for (const section of sections) {
    let titled = false;
    for (const row of section.rows) {
      const text = line(row, data, t, lang);
      const cost = text.length + 1 + (titled ? 0 : section.title.length + 2);
      if (left > 0 || used + cost > BUDGET) {
        left += 1;
        continue;
      }
      if (!titled) {
        lines.push("", section.title);
        titled = true;
      }
      lines.push(text);
      used += cost;
    }
  }
  if (left > 0) lines.push(t("review.prompt_more", { count: left }));
  return [...head, ...lines, "", tail].join("\n");
}
