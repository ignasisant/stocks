/**
 * The one view every viewed tool shares, picked by `structuredContent.kind`.
 *
 * Before the host has sent a result it says so; a result with no view of its
 * own (or an error) is left to the text Claude already has, with one line
 * saying as much rather than an empty frame. Each kind ends with the way back
 * to the page in TopStocks it summarises.
 */

import { shortDay } from "./format";
import { Overview } from "./Overview";
import { Performance } from "./Performance";
import type {
  Overview as OverviewData,
  Performance as PerformanceData,
  Words,
} from "./types";
import type { ToolResult } from "./bridge";

/** Where "Open in TopStocks" goes for each kind: the tab it summarises. */
const PAGES: Record<string, string> = {
  overview: "/portfolio",
  performance: "/portfolio?tab=risk",
};

/** The text of an error result, which is the reason in words. */
function said(result: ToolResult): string {
  return (result.content ?? [])
    .map((part) => (part.type === "text" ? (part.text ?? "") : ""))
    .join("\n")
    .trim();
}

export function View({ result, words }: { result: ToolResult | null; words: Words }) {
  const { t, locale } = words;
  if (result === null) return <p className="v-wait">{t("connector.view_waiting")}</p>;
  if (result.isError) return <p className="v-note">{said(result)}</p>;

  const data = result.structuredContent ?? {};
  const kind = typeof data.kind === "string" ? data.kind : "";
  let title: string;
  let sub = "";
  let body;
  if (kind === "overview") {
    title = t("connector.view_overview_title");
    body = <Overview data={data as OverviewData} words={words} />;
  } else if (kind === "performance") {
    const perf = data as PerformanceData;
    title = t("connector.view_performance_title");
    sub = t(`connector.view_window_${perf.performance.window}`);
    body = <Performance data={perf} words={words} />;
  } else {
    return <p className="v-note">{t("connector.view_unknown")}</p>;
  }

  const stale = typeof data.stale_since === "string" ? data.stale_since : null;
  const page = PAGES[kind] ?? "/";
  return (
    <article className="v-card">
      <header className="v-head">
        <h1>{title}</h1>
        {sub && <span className="v-sub">{sub}</span>}
      </header>
      {body}
      {stale && (
        <p className="v-note">
          {t("connector.view_stale", { time: shortDay(stale, locale) })}
        </p>
      )}
      <footer className="v-foot">
        <a
          href={page}
          onClick={(event) => {
            event.preventDefault();
            words.open(page);
          }}
        >
          {t("connector.view_open")} ↗
        </a>
      </footer>
    </article>
  );
}
