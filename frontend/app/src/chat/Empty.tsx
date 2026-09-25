/**
 * The opening screen: what the assistant can do, and three ways in.
 *
 * An empty scroll region and a placeholder said nothing — not that the
 * assistant can see the reader's own book, not that it reads a pasted link.
 * The ticker count is the line that proves the first claim, so it is counted
 * from the account rather than written into the copy.
 *
 * Two requests, and only ever for an empty thread. `/portfolio/positions` is
 * the priced one, which is why it is not fetched when there is a conversation
 * to draw instead: it decides which three suggestions are worth offering, and
 * a fresh account offered "Summarise my portfolio" is offered a question
 * nothing can answer.
 *
 * The capability rows do not mention dropping a statement into the chat. That
 * is the one line on this screen the React drawer cannot honour — see the
 * note in `Composer.tsx`.
 */

import { get } from "../shell/api";
import { useT } from "../shell/i18n";
import { useApi } from "../shell/useApi";
import { CAP_PATHS, CapGlyph } from "./icons";
import { Inline } from "./markdown";

/**
 * With a ledger behind it the assistant's best trick is the reader's own book,
 * so those are the questions the opening screen offers. A fresh account has no
 * ledger and would be offered three questions it cannot answer, so it gets the
 * watchlist set instead — live quotes, fundamentals and the earnings calendar
 * all work with no import at all.
 */
const BOOK = [
  "chat.starter_summary",
  "chat.starter_concentration",
  "chat.starter_earnings_week",
];
const FRESH = ["chat.starter_movers", "chat.starter_compare", "chat.starter_earnings"];

/** Analyse what you hold · research with the web · import a statement · alert. */
const CAPS = [
  ["chat.cap_analyze", CAP_PATHS[0]],
  ["chat.cap_web", CAP_PATHS[1]],
  ["chat.cap_import", CAP_PATHS[2]],
  ["chat.cap_alerts", CAP_PATHS[3]],
] as const;

type Book = { positions: { ticker: string; shares: number }[] };
type Watch = { entries: { ticker: string; favorite: boolean }[] };

/**
 * Two tickers to name in the suggestions: favorites first, then order.
 *
 * Falls back to the two the copy reads least oddly with when the watchlist is
 * short or empty — a suggestion is only ever a prefilled question, so a
 * generic pair is better than hiding the row.
 */
function pair(entries: Watch["entries"]): [string, string] {
  const picked = [
    ...entries.filter((e) => e.favorite).map((e) => e.ticker),
    ...entries.map((e) => e.ticker),
    "AAPL",
    "MSFT",
  ];
  return [picked[0] as string, picked.find((x) => x !== picked[0]) as string];
}

export function Empty({ onAsk }: { onAsk: (question: string) => void }) {
  const t = useT();
  const account = useApi(async () => {
    const [book, watch] = await Promise.all([
      get<Book>("/portfolio/positions"),
      get<Watch>("/watchlist"),
    ]);
    return {
      held: book.positions.filter((p) => p.shares).length,
      entries: watch.entries,
    };
  }, []);

  const loaded = account.state === "loaded" ? account.data : null;
  const held = loaded?.held ?? 0;
  const [a, b] = pair(loaded?.entries ?? []);
  // A failed read shows no number at all rather than a zero: "it reads your 0
  // positions" is a claim about the account, and this one was never counted.
  const intro =
    account.state !== "loaded"
      ? ""
      : held
        ? t("chat.empty_body", { n: held })
        : t("chat.empty_body_new", { n: loaded?.entries.length ?? 0 });
  const starters = held ? BOOK : FRESH;

  return (
    <div className="ag-chat-empty">
      <div className="ag-chat-empty-head">
        <span className="ag-chat-empty-title">{t("chat.empty_title")}</span>
        {intro && <span className="ag-chat-empty-body">{intro}</span>}
      </div>
      <div className="ag-chat-caps">
        {CAPS.map(([key, paths]) => (
          <div className="ag-chat-cap" key={key}>
            <CapGlyph paths={paths ?? ""} />
            <span>
              <Inline text={t(key)} />
            </span>
          </div>
        ))}
      </div>
      <div className="ag-chat-starters">
        <div className="ag-chat-group">{t("chat.start_with")}</div>
        {account.state === "loading" ? (
          <div className="ag-skeleton" aria-hidden="true">
            <div className="ag-skeleton-row" />
            <div className="ag-skeleton-row" />
            <div className="ag-skeleton-row" />
          </div>
        ) : (
          starters.map((key) => {
            const prompt = t(key, { a, b });
            return (
              <button
                type="button"
                className="ag-chat-starter"
                key={key}
                onClick={() => onAsk(prompt)}
              >
                {prompt}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
