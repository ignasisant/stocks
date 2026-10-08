/**
 * Home — the daily glance: the market, what's new, and the key portfolio
 * figures.
 *
 * The running order is the reader's. The page draws the cards in
 * `prefs.home_layout` (see `cards.ts`), and the default a new account gets is
 * the order the page always had, with the market strip on top: the market,
 * the AI "Daily action" briefing, the Portfolio page's headline metrics, the
 * movers beside the 52-week extremes, the earnings calendar, the recent
 * transactions, the watchlist groups. Risk, dividends, the tax year and
 * sector rotation wait in the editor's tray. Every ticker cell links to its
 * own page; the full ledger analytics stay on Portfolio.
 *
 * Cards are a fixed width each — a full row or half of one — and flow two to
 * a row on a wide page. A half card with no half beside it runs the full row,
 * and a card with nothing to say (no movers, no transactions) renders nothing
 * and takes no room.
 *
 * Each card carries its own query, so a throttled price burst takes down the
 * card that needed it and nothing else, and a hidden card asks for nothing.
 * The one exception is the glance and the movers, which read the same book
 * (`useBook`, called here) and fail together on purpose.
 *
 * The first-run card opens the page, above the briefing: what is worth
 * connecting, and what already works without connecting anything, is the
 * first thing a new account needs and the last thing a settled one reads —
 * which is why it collapses to two lines and then to nothing.
 *
 * Deliberately not here, because another pass owns them: the chat drawer and
 * the guided tour, both mounted by the shell.
 *
 * For a guest this page loses everything that is *somebody's* and keeps
 * everything that is the market's: no briefing, no glance, no recent
 * transactions — the glance is per-account and a guest has no ledger — but the
 * market strip, the watchlist, the earnings calendar and the 52-week extremes
 * all stay, because they are the same for everybody and they are what makes
 * the demo worth walking into. A guest has no prefs to write, so "Customise"
 * offers a sign-in instead of the editor.
 */

import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { get, send } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useT } from "../../shell/i18n";
import { GuestBanner, SignInWall } from "../../shell/guest";
import { useGuest, useSession } from "../../shell/session";
import { Skeleton } from "../../shell/Layout";
import { Link } from "../../shell/router";
import { Icon } from "../../shell/Icon";
import { Daily } from "./Daily";
import { FirstRun } from "./FirstRun";
import { SetupCard } from "./Setup";
import { Glance, MoversSlot, useBook } from "./Glance";
import { MarketCard } from "./Market";
import { EarningsCard } from "./Earnings";
import { RecentTransactions } from "./Transactions";
import { ExtremesCard, moverRows, useExtremes } from "./Extremes";
import { WatchlistGroups } from "./Watchlist";
import { DividendsCard, RiskCard, RotationCard, TaxCard } from "./Extras";
import {
  rememberLayout,
  resolveLayout,
  storedLayout,
  visibleCards,
  type CardId,
  type Slot,
} from "./cards";
import type { Transactions } from "./types";
import "./home.css";

// The drag library rides with the editor, not with every Home visit.
const Editor = lazy(() => import("./Editor"));

export default function Page() {
  const t = useT();
  // Bumped by "Refresh prices": every section whose figures come off a quote
  // burst takes it as a dependency and asks again. The ledger below does not —
  // the refresh drops the price caches and leaves the ledger's hot.
  const [nonce, setNonce] = useState(0);
  const guest = useGuest();
  const session = useSession();
  const [layout, setLayout] = useState<Slot[]>(() =>
    resolveLayout(storedLayout(session.prefs.home_layout)),
  );
  const [editing, setEditing] = useState(false);
  const [nudge, setNudge] = useState(false);
  // Closing the editor hands focus back to the button that opened it.
  const customizeRef = useRef<HTMLButtonElement>(null);
  const [refocus, setRefocus] = useState(false);
  useEffect(() => {
    if (!refocus || editing) return;
    customizeRef.current?.focus();
    setRefocus(false);
  }, [refocus, editing]);
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

  const cards = visibleCards(layout, guest);
  const shown = new Set<CardId>(cards.map((card) => card.id));
  // One read behind the glance and the movers, and none when neither is on
  // the page.
  const book = useBook(nonce, !guest && (shown.has("glance") || shown.has("movers")));
  // Read here rather than in its card: the movers beside it match its rows.
  const extremes = useExtremes(nonce, shown.has("extremes"));

  const draw = (id: CardId): ReactNode => {
    switch (id) {
      case "market":
        return <MarketCard nonce={nonce} />;
      case "daily":
        return <Daily />;
      case "glance":
        return <Glance query={book} ledger={ledger} />;
      case "movers":
        return (
          <MoversSlot
            query={book}
            alone={!shown.has("glance")}
            rows={moverRows(extremes)}
          />
        );
      case "extremes":
        return <ExtremesCard query={extremes} />;
      case "earnings":
        return <EarningsCard />;
      case "transactions":
        // Renders nothing for a book with no ledger; its slot then collapses.
        return <RecentTransactions query={ledger} />;
      case "watchlist":
        return (
          <WatchlistGroups
            nonce={nonce}
            onRefresh={refresh}
            holdsPositions={ledger.state === "loaded" && ledger.data.total > 0}
          />
        );
      case "risk":
        return <RiskCard />;
      case "dividends":
        return <DividendsCard />;
      case "tax":
        return <TaxCard />;
      case "rotation":
        return <RotationCard />;
    }
  };

  // No row of its own: it sits at the end of whichever card leads the page's
  // heading line (`.hm-slot-lead` in home.css), so the page starts with
  // content rather than with a toolbar.
  const customize = (
    <button
      type="button"
      ref={customizeRef}
      className="hm-customize"
      aria-label={t("home.customize_label")}
      title={t("home.customize_label")}
      aria-expanded={guest ? nudge : undefined}
      onClick={() => (guest ? setNudge((on) => !on) : setEditing(true))}
    >
      <Icon name="dashboard_customize" size={16} />
      <span className="hm-customize-text">{t("home.customize")}</span>
    </button>
  );

  return (
    <div className="hm-page">
      {/* Above the checklist: what to do first comes before what is switched
          on. Both vanish once they are answered.

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
              this link sits in the banner: Home's own glance is per-account and
              stays empty, but Portfolio runs end to end on the shared demo
              book. Without this the demo is a screen a visitor has to guess
              their way to. */}
          <Link className="ag-btn" page="portfolio">
            {t("home.guest_try_demo")}
          </Link>
        </GuestBanner>
      ) : (
        <FirstRun ledger={ledger} />
      )}
      <SetupCard />
      {editing ? (
        <Suspense fallback={<Skeleton rows={6} />}>
          <Editor
            layout={layout}
            onClose={(saved) => {
              if (saved !== undefined) {
                rememberLayout(saved);
                setLayout(resolveLayout(saved));
              }
              setEditing(false);
              setRefocus(true);
            }}
          />
        </Suspense>
      ) : (
        <>
          {guest && nudge ? <SignInWall text="home.customize_guest" /> : null}
          {cards.length === 0 ? (
            // Every card put away: the control has no heading to sit in, and
            // is the only way back.
            <div className="hm-slot hm-slot-lead">{customize}</div>
          ) : null}
          <div className="hm-grid">
            {cards.map((card, i) => (
              <div
                key={card.id}
                className={`hm-slot hm-slot-${card.span}${i === 0 ? " hm-slot-lead" : ""}`}
                data-card={card.id}
              >
                {i === 0 ? customize : null}
                {draw(card.id)}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
