/**
 * Portfolio — everything the transaction ledger derives: open positions and
 * P/L, allocation and risk, the realized result under the filer's own
 * jurisdiction, dividends, and what trading it all cost.
 *
 * Six tabs, the overview first, and the active one rides the URL as a slug (`?tab=fees`) rather
 * than as its label: labels are localized, and a bookmark made in Spanish has
 * to open the same tab in English. `setParams` writes it without a history
 * entry — switching a tab is not a navigation the back button should have to
 * walk back through.
 *
 * Only the open tab's component is mounted, so only its fetch runs: the
 * price-and-profile burst behind "Allocation & risk" must not block the tabs
 * that do not need it.
 */

import { TypeInstead } from "../../ui/TypeInstead";
import { useState } from "react";

import { get, send } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { GuestBanner } from "../../shell/guest";
import { useCurrency, useGuest } from "../../shell/session";
import { compactMoneyIn } from "../../shell/format";
import type { Summary, Transactions } from "./api";
import { Tabs } from "../../ui/Tabs";
import { Empty, Warn } from "./ui";
import Overview from "./Overview";
import Positions from "./Positions";
import Risk from "./Risk";
import Projection from "./Projection";
import Tax from "./Tax";
import Dividends from "./Dividends";
import Fees from "./Fees";
import "./portfolio.css";

const TABS = [
  ["overview", "portfolio.tab_overview", Overview],
  ["positions", "portfolio.tab_positions", Positions],
  ["risk", "portfolio.tab_alloc_risk", Risk],
  ["projection", "portfolio.tab_projection", Projection],
  ["tax", "portfolio.tab_realized_tax", Tax],
  ["dividends", "portfolio.tab_dividends", Dividends],
  ["fees", "portfolio.tab_fees", Fees],
] as const;

/**
 * The example book: an offer while the ledger is empty, a warning once it is
 * not empty because of it.
 *
 * Both halves are here rather than inside a tab because the claim is about
 * every figure on the page at once. Nothing is shown twice: an empty book
 * cannot be a demo book, and a demo book is not empty.
 *
 * The button reloads the ledger call rather than guessing at the new state.
 * Seeding refuses a book that holds anything (409) and clearing refuses one
 * holding no demo rows (404), so the server's answer is the only one worth
 * drawing — and a failure leaves the page saying what is actually there.
 */
function DemoBook({ book, onChange }: { book: Transactions; onChange: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  const act = async (verb: "POST" | "DELETE") => {
    setBusy(true);
    try {
      await send(verb, "/portfolio/demo");
    } catch {
      // Refused, or the network went. Re-reading the ledger below says which
      // book is really there, which is the honest answer either way.
    } finally {
      setBusy(false);
      onChange();
    }
  };

  if (book.demo) {
    return (
      <div className="pf-demo">
        <p>{t("portfolio.demo_banner")}</p>
        <button
          className="ag-btn"
          disabled={busy}
          onClick={() => void act("DELETE")}
          type="button"
        >
          {t("portfolio.demo_remove")}
        </button>
        <TypeInstead />
      </div>
    );
  }
  if (book.total > 0) return null;
  return (
    <div className="pf-demo">
      <p>{t("portfolio.demo_offer_caption")}</p>
      <button
        className="ag-btn"
        disabled={busy}
        onClick={() => void act("POST")}
        type="button"
      >
        {t("portfolio.demo_offer_button")}
      </button>
      <TypeInstead />
    </div>
  );
}

export default function Page() {
  const t = useT();
  const { params, setParams } = useRoute();
  const guest = useGuest();

  // One cheap call decides whether there is a book at all: the ledger is the
  // source of every tab, and an account with no transactions should see the
  // way in rather than five empty tabs.
  const ledger = useApi(
    () => get<Transactions>("/portfolio/transactions", { limit: 1 }),
    [],
  );

  // Ledger rows that never made a position — only deposits, fees or rows the
  // replay could not match — leave every tab with nothing to say. The page
  // says so once and stops rather than drawing five empty tabs; the same
  // cached summary the Positions tab reads answers it here. Never blocking:
  // while it loads, or if it fails, the tabs draw as usual.
  const base = useCurrency();
  const summary = useApi(() => get<Summary>("/portfolio/summary", { base }), [base]);
  const nothingHeld =
    summary.state === "loaded" &&
    summary.data.positions === 0 &&
    summary.data.realized === null;
  // Seeding or removing the demo rewrites the book both queries read, so both
  // are asked again: the ledger alone would leave `nothingHeld` judging the
  // new book by the empty one's summary until the next page load.
  const onDemo = (reload: () => void) => () => {
    reload();
    if (summary.state === "loaded") summary.reload();
  };

  const slug = params.get("tab") ?? "";
  const active = TABS.find((tab) => tab[0] === slug) ?? TABS[0];
  const Tab = active[2];

  // What each tab holds, said on the tab itself. Only what the summary above
  // already answers: a badge that cost a fetch of its own would hold the
  // strip back for the sake of a hint.
  const lang = useLang();
  const compact = compactMoneyIn(lang, base);
  const badge = (id: string): string | null => {
    if (summary.state !== "loaded") return null;
    if (id === "overview") return compact(summary.data.value);
    if (id === "positions") return String(summary.data.positions);
    return null;
  };
  const unpriced = summary.state === "loaded" ? summary.data.unpriced : 0;

  return (
    <>
      <h1>{t("nav.portfolio")}</h1>
      <Loaded query={ledger} skeleton={<Skeleton rows={6} />}>
        {(state, reload) =>
          state.total === 0 ? (
            <>
              <Empty
                title={t("portfolio.empty_ledger_title")}
                body={t("portfolio.empty_ledger_body")}
                cta={{ label: t("common.cta_import"), page: "import" }}
              />
              {/* A guest reaching this means the shared demo book is empty —
                  the bucket was away at boot, or somebody wiped it. There is
                  nothing for them to seed and nowhere for them to import to, so
                  the banner is the whole of the answer. */}
              {guest ? (
                <GuestBanner text="portfolio.guest_demo_banner" />
              ) : (
                <DemoBook book={state} onChange={onDemo(reload)} />
              )}
            </>
          ) : (
            <>
              {/* The page that costs the least to open and demos the most: all
                  five tabs run unchanged over the shared demo book, so this is
                  the only edit the whole of Portfolio needs. What changes is
                  the strip above them — a guest is told these trades are
                  invented and offered a way to import real ones, where an
                  account is offered the seed/remove control it can actually
                  press. */}
              {guest ? (
                <GuestBanner text="portfolio.guest_demo_banner" />
              ) : (
                <DemoBook book={state} onChange={onDemo(reload)} />
              )}
              {nothingHeld ? (
                <Warn>{t("portfolio.ledger_no_positions")}</Warn>
              ) : (
                <>
                  <div className="pf-tabbar">
                    <Tabs
                      className="pf-tabs"
                      label={t("nav.portfolio")}
                      items={TABS.map(([id, label]) => ({
                        id,
                        label: (
                          <>
                            {t(label)}
                            {badge(id) ? (
                              <small className="pf-tab-badge">{badge(id)}</small>
                            ) : null}
                          </>
                        ),
                      }))}
                      active={active[0]}
                      onPick={(tab) => setParams({ tab })}
                    />
                  </div>
                  {/* What is missing says so at the top, not in a footnote of
                      the tab it happens to touch. */}
                  {unpriced > 0 ? (
                    <div className="pf-notice" role="status">
                      <span>
                        {t("portfolio.unpriced_notice", { n: unpriced })}
                        {summary.state === "loaded" && summary.data.unlisted?.length
                          ? ` (${summary.data.unlisted.join(", ")})`
                          : ""}
                      </span>
                      {active[0] !== "positions" ? (
                        <button
                          className="ag-btn"
                          type="button"
                          onClick={() => setParams({ tab: "positions" })}
                        >
                          {t("portfolio.unpriced_see")}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  <Tab />
                </>
              )}
            </>
          )
        }
      </Loaded>
    </>
  );
}
