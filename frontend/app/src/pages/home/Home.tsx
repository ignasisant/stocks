/**
 * Home — the daily glance: what's new, plus the key portfolio figures.
 *
 * Same running order as `web/app_pages/home.py`, which is the specification:
 * the AI "Daily action" card opens the page — one briefing a day on what to
 * look at — then the Portfolio page's headline metrics with the movers card
 * under them, then the "What's new" cards (earnings, recent transactions,
 * 52-week extremes), then the watchlist groups collapsed into expanders.
 * Every ticker cell links to its own page; the full ledger analytics stay on
 * Portfolio.
 *
 * Each card carries its own query, so a throttled price burst takes down the
 * card that needed it and nothing else — which is what the Streamlit page's
 * per-section toasts and cleared slots do. The one exception is the glance and
 * its movers, which read the same book and fail together on purpose.
 *
 * The first-run card opens the page, above the briefing, exactly as it does in
 * Streamlit: what is worth connecting, and what already works without
 * connecting anything, is the first thing a new account needs and the last
 * thing a settled one reads — which is why it collapses to two lines and then
 * to nothing.
 *
 * Deliberately not here, because another pass owns them: the chat drawer and
 * the guided tour, both mounted by the shell.
 *
 * For a guest this page loses everything that is *somebody's* and keeps
 * everything that is the market's, which is exactly what `home.py` does: no
 * briefing, no glance, no recent transactions — its glance is per-account and
 * `home.py` reads the ledger as `DB if is_logged_in() else None` — but the
 * watchlist, the earnings calendar and the 52-week extremes all stay, because
 * they are the same for everybody and they are what makes the demo worth
 * walking into.
 */

import { useCallback, useState } from "react";
import { get, send } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useT } from "../../shell/i18n";
import { GuestBanner, SignedInOnly } from "../../shell/guest";
import { useGuest } from "../../shell/session";
import { Link } from "../../shell/router";
import { Daily } from "./Daily";
import { FirstRun } from "./FirstRun";
import { SetupCard } from "./Setup";
import { Glance } from "./Glance";
import { EarningsCard } from "./Earnings";
import { RecentTransactions } from "./Transactions";
import { ExtremesCard } from "./Extremes";
import { WatchlistGroups } from "./Watchlist";
import { plain } from "./format";
import type { Transactions } from "./types";
import "./home.css";

export default function Page() {
  const t = useT();
  // Bumped by "Refresh prices": every section whose figures come off a quote
  // burst takes it as a dependency and asks again. The ledger below does not —
  // the Streamlit button drops the price caches and leaves the ledger's hot.
  const [nonce, setNonce] = useState(0);
  const guest = useGuest();
  // The server's caches go first (`POST /home/refresh`), or asking again would
  // answer from the very entries the reader pressed the button to get past. A
  // guest may not write, so a guest's press is the re-ask alone — which still
  // picks up anything whose short TTL has rolled over. A refused or failed
  // drop is not worth an error: the re-ask happens either way.
  const refresh = useCallback(() => {
    const drop = guest
      ? Promise.resolve()
      : send("POST", "/home/refresh").catch(() => undefined);
    void drop.then(() => setNonce((n) => n + 1));
  }, [guest]);
  // A `useGuest()` boolean rather than a `<SignedInOnly>` wrapper, because this
  // query belongs to the page and is shared by three children: not rendering
  // them cannot un-fire a hook their parent already called. So the skip goes
  // where the call is. Same idiom as the conditional fetch in `Ticker.tsx`.
  const ledger = useApi<Transactions>(
    () =>
      guest
        ? Promise.resolve({ total: 0, transactions: [] } satisfies Transactions)
        : get<Transactions>("/portfolio/transactions", { limit: 5 }),
    [guest],
  );

  return (
    <div className="hm-page">
      {/* Above the checklist, as Streamlit draws it: what to do first comes
          before what is switched on. Both vanish once they are answered.

          For a guest the checklist has nothing to check off, so the banner
          takes its place and says what this screen is instead. The setup card
          below stays: its first pending row *is* signing in, which makes it the
          most useful thing on a guest's Home rather than a tease — and its
          dismiss only appears once every row is done, so a guest never sees a
          control that would need a write. */}
      {guest ? (
        <GuestBanner
          text="home.guest_banner"
          short="home.guest_banner_short"
          dismissible="home"
        >
          {/* Where a guest session is actually worth something, and the reason
              `home.py` puts this link in the same row: Home's own glance is
              per-account and stays empty, but Portfolio runs end to end on the
              shared demo book. Without this the demo is a screen a visitor has
              to guess their way to. */}
          <Link className="ag-btn" page="portfolio">
            {t("home.guest_try_demo")}
          </Link>
        </GuestBanner>
      ) : (
        <FirstRun ledger={ledger} />
      )}
      <SetupCard />
      {/* A briefing is generated per account on a daily budget and the glance
          is the reader's own book. Wrapped rather than emptied, so neither
          spends a request a guest may not use the answer to. */}
      <SignedInOnly>
        <Daily />
        <Glance nonce={nonce} ledger={ledger} />
      </SignedInOnly>
      <section className="hm-section">
        <h2 className="hm-h2">{plain(t("home.whats_new"))}</h2>
        <EarningsCard />
        {/* Two per row on desktop, stacked on a phone. The transactions strip
            renders nothing for a book with no ledger, and the extremes card
            then takes the first cell rather than leaving a hole. */}
        <div className="hm-pair">
          {/* The strip already renders nothing for a book with no ledger, and
              the extremes card then takes the first cell rather than leaving a
              hole — which is exactly what a guest gets. */}
          <SignedInOnly>
            <RecentTransactions query={ledger} />
          </SignedInOnly>
          <ExtremesCard nonce={nonce} />
        </div>
      </section>
      <WatchlistGroups
        nonce={nonce}
        onRefresh={refresh}
        holdsPositions={ledger.state === "loaded" && ledger.data.total > 0}
      />
    </div>
  );
}
