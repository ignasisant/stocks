/**
 * The `navigate` tool's page button: an answer offering to open a page.
 *
 * AG-UI calls it a frontend tool — the model proposes, the client runs it —
 * and here running it is the reader's press, not the stream's: an answer that
 * moved the page under someone mid-sentence would be the assistant taking the
 * wheel. The server has already held the call to `chat/navigate.py`'s page
 * table, so what arrives is a page this shell has; the tab labels below are
 * that table's, and `tests/test_chat_navigate.py` keeps the two in step.
 */

import { useT } from "../shell/i18n";
import { canonical, pageFor } from "../shell/pages";
import { useRoute } from "../shell/router";
import { phone } from "./GuideCard";

/** Each linkable tab's label key, by page slug and `?tab=` value. */
const TAB_LABELS: Record<string, Record<string, string>> = {
  portfolio: {
    overview: "portfolio.tab_overview",
    positions: "portfolio.tab_positions",
    risk: "portfolio.tab_alloc_risk",
    projection: "portfolio.tab_projection",
    tax: "portfolio.tab_realized_tax",
    dividends: "portfolio.tab_dividends",
    fees: "portfolio.tab_fees",
  },
  sentiment: {
    indices: "sentiment.indices_title",
    gauges: "sentiment.risk_title",
    rates: "sentiment.rates_title",
    inflation: "sentiment.inflation_title",
    rotation: "sentiment.rotation_title",
    factors: "sentiment.factors_title",
    cross: "sentiment.cross_title",
  },
  profile: {
    prefs: "profile.preferences",
    iv: "profile.iv_section",
    watch: "profile.watchlist",
    notify: "profile.notifications",
  },
};

const text = (value: unknown) => (typeof value === "string" ? value : "");

/**
 * "Open Portfolio · Tax", and the press that goes there. On a phone the drawer
 * steps aside afterwards, as the walkthrough's jump does: it is the whole
 * viewport there, and staying open would hide the page it just opened.
 */
export function PageLink({
  args,
  onLeave,
}: {
  args: Record<string, unknown>;
  onLeave: () => void;
}) {
  const t = useT();
  const { go } = useRoute();
  const page = pageFor(canonical(text(args.page)));
  const tab = text(args.tab);
  const ticker = text(args.ticker);
  const tabLabel = TAB_LABELS[page.slug]?.[tab];
  const name = ticker || t(page.label);
  const label = tabLabel
    ? t("chat.open_tab", { page: name, tab: t(tabLabel) })
    : t("chat.open_page", { page: name });
  const params: Record<string, string> = ticker ? { ticker } : tabLabel ? { tab } : {};
  return (
    <div className="ag-guide-acts">
      <button
        type="button"
        className="ag-chat-btn"
        onClick={() => {
          go(page.slug, params);
          if (phone()) onLeave();
        }}
      >
        {label}
      </button>
    </div>
  );
}
