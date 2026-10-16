/**
 * What each name returned over the window the reader picks, beside the S&P
 * 500 and its sector's ETF — the tables' last three columns.
 *
 * Its own request (`/review/returns`), asked once the verdicts are on screen:
 * five years of closes per name is not something the plan should wait for.
 * Until it lands the cells hold an ellipsis; a name the server could not
 * measure reads as the page's "n/a".
 *
 * One window for both tables (`?ret=`), so a held name and an outside one
 * read over the same stretch. Every figure is in the page's currency and ends on the
 * same day for every name, so a gap is a gap in performance.
 */

import { type ReactNode, createContext, useContext, useEffect, useState } from "react";
import { get } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Segmented } from "../../ui/Segmented";
import { percent } from "./format";
import type { NameReturns, ReviewReturns } from "./types";

const WINDOWS = ["1m", "6m", "1y", "2y"] as const;
export type ReturnWindow = (typeof WINDOWS)[number];

/** The S&P 500 every gap is measured against — `routes.review.INDEX`. */
export const INDEX = "SPY";

const RETRY_MS = 3000;

const DEFAULT_SPAN: ReturnWindow = "1y";

export function parseSpan(raw: string | null): ReturnWindow {
  return (WINDOWS as readonly string[]).includes(raw ?? "")
    ? (raw as ReturnWindow)
    : DEFAULT_SPAN;
}

/** One name's three cells: undefined while asking, null when not measured. */
export type Measured = {
  own: number | null;
  index: number | null;
  sector: number | null;
  etf: string | null;
};

type Bundle = {
  span: ReturnWindow;
  setSpan: (next: ReturnWindow) => void;
  of: (symbol: string) => Measured | null | undefined;
};

const Context = createContext<Bundle | null>(null);

/** The figures behind every row of the page, read once for `names`. */
export function ReturnsProvider({
  names,
  base,
  children,
}: {
  names: string[];
  base: string;
  children: ReactNode;
}) {
  // On the URL with the page's filters: a ticker added redraws the whole
  // read, and the window the reader picked has to outlive it.
  const { params, setParams } = useRoute();
  const span = parseSpan(params.get("ret"));
  const setSpan = (next: ReturnWindow) =>
    setParams({ ret: next === DEFAULT_SPAN ? undefined : next });
  const asked = names.join(",");
  const query = useApi(
    () => get<ReviewReturns>("/review/returns", { base, names: asked }),
    [base, asked],
  );
  // A wide book read cold answers with the names that arrived in time; ask
  // once more for the rest, as the review itself does.
  const [retried, setRetried] = useState<string | null>(null);
  const key = `${base}|${asked}`;
  useEffect(() => {
    if (query.state !== "loaded" || !query.data.pending || retried === key) return;
    const timer = setTimeout(() => {
      setRetried(key);
      query.reload();
    }, RETRY_MS);
    return () => clearTimeout(timer);
  }, [query, retried, key]);

  const data = query.state === "loaded" ? query.data : null;
  const of = measure(data, span, query.state === "loading");
  return <Context.Provider value={{ span, setSpan, of }}>{children}</Context.Provider>;
}

/** A lookup from symbol to its cells over `span`, from one answer. */
export function measure(
  data: ReviewReturns | null,
  span: ReturnWindow,
  loading: boolean,
): (symbol: string) => Measured | null | undefined {
  if (!data) return () => (loading ? undefined : null);
  const byName = new Map<string, NameReturns>(data.names.map((n) => [n.ticker, n]));
  const bench = new Map<string, NameReturns>(data.benchmarks.map((n) => [n.ticker, n]));
  const at = (row: NameReturns | undefined) => row?.returns[span] ?? null;
  const index = at(bench.get(INDEX));
  return (symbol) => {
    const row = byName.get(symbol.toUpperCase());
    if (!row) return null;
    const own = at(row);
    const sector = row.sector_etf ? at(bench.get(row.sector_etf)) : null;
    return {
      own,
      index: own !== null && index !== null ? own - index : null,
      sector: own !== null && sector !== null ? own - sector : null,
      etf: row.sector_etf,
    };
  };
}

/** The page's window and lookup; null outside a provider (the import wall). */
export function useReturns(): Bundle | null {
  return useContext(Context);
}

/** The window picker over a table. */
export function WindowPicker() {
  const t = useT();
  const bundle = useReturns();
  if (!bundle) return null;
  return (
    <Segmented
      label={t("review.window")}
      items={WINDOWS.map((id) => ({ id, label: t(`ticker.period_${id}`) }))}
      value={bundle.span}
      onPick={bundle.setSpan}
      className="ag-rev-window"
    />
  );
}

function tone(value: number | null): string | undefined {
  if (value === null || value === 0) return undefined;
  return value > 0 ? "ag-rev-tone-up" : "ag-rev-tone-down";
}

/** A return or a gap as the cells print it: signed, one decimal. */
function useReturnText() {
  const t = useT();
  const lang = useLang();
  const signed = (value: number) =>
    `${value > 0 ? "+" : ""}${percent(value, lang) ?? ""}`;
  return {
    own: (value: number) => signed(value),
    gap: (value: number) =>
      t("review.pp", {
        value: `${value > 0 ? "+" : ""}${percent(value, lang)?.replace(/\s?%/, "") ?? ""}`,
      }),
  };
}

/** The three heads, in table order. */
export function ReturnHeads({
  head,
}: {
  head: (label: string, help: string) => ReactNode;
}) {
  const t = useT();
  const bundle = useReturns();
  if (!bundle) return null;
  const span = t(`ticker.period_${bundle.span}`);
  return (
    <>
      {head(t("review.col_return", { span }), t("review.col_return_help"))}
      {head(t("review.col_vs_index"), t("review.col_vs_index_help"))}
      {head(t("review.col_vs_sector"), t("review.col_vs_sector_help"))}
    </>
  );
}

/** One row's three cells. */
export function ReturnCells({ symbol, na }: { symbol: string; na: string }) {
  const bundle = useReturns();
  const text = useReturnText();
  if (!bundle) return null;
  const cells = bundle.of(symbol);
  if (cells === undefined) {
    return (
      <>
        {[0, 1, 2].map((i) => (
          <td key={i} className="ag-rev-wait" aria-busy="true">
            …
          </td>
        ))}
      </>
    );
  }
  return (
    <>
      <td className={tone(cells?.own ?? null)}>
        {cells?.own != null ? text.own(cells.own) : na}
      </td>
      <td className={tone(cells?.index ?? null)}>
        {cells?.index != null ? text.gap(cells.index) : "—"}
      </td>
      <td
        className={tone(cells?.sector ?? null)}
        title={cells?.etf ? `vs ${cells.etf}` : undefined}
      >
        {cells?.sector != null ? text.gap(cells.sector) : "—"}
      </td>
    </>
  );
}

/** The narrow row's line: "1A +12,3 %", or nothing until it is known. */
export function useReturnLine(): (symbol: string) => string | null {
  const t = useT();
  const bundle = useReturns();
  const text = useReturnText();
  return (symbol) => {
    const own = bundle?.of(symbol)?.own;
    if (own == null || !bundle) return null;
    return `${t(`ticker.period_${bundle.span}`)} ${text.own(own)}`;
  };
}
