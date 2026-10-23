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
 * Nor does a card below the fold ask for anything until the reader scrolls
 * towards it (`LazySlot`, on `useInView`): the page's first requests go to
 * what is on screen, and the rest follow the scroll. The lead card is drawn
 * at once — it is on screen on arrival — and the page-level reads (the book
 * behind the glance and the movers, the extremes) wait for their cards the
 * same way. The ledger is the exception: one small read three cards share,
 * cheaper to have than to time.
 *
 * The start card opens the page, above the briefing: a line of icons, each a
 * door into the section that switches it on, is the first thing a new account
 * needs and the last thing a settled one reads — which is why it is gone once
 * everything on it is done.
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
import { GuestBanner, SignInWall, type GuestHighlight } from "../../shell/guest";
import { useGuest, useSession } from "../../shell/session";
import { Skeleton } from "../../shell/Layout";
import { Link } from "../../shell/router";
import { Icon } from "../../shell/Icon";
import { useInView } from "../../shell/useInView";
import { Daily } from "./Daily";
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

/**
 * What an account adds over this guest Home. The AI gets the cards — it is the
 * part a visitor cannot try here at all (the drawer is closed to guests) — and
 * the rest one ticked line under them.
 */
const GUEST_HIGHLIGHTS: GuestHighlight[] = [
  { icon: "forum", title: "home.guest_ai_chat", body: "home.guest_ai_chat_body" },
  { icon: "wb_sunny", title: "home.guest_ai_brief", body: "home.guest_ai_brief_body" },
  {
    icon: "lightbulb",
    title: "home.guest_ai_memory",
    body: "home.guest_ai_memory_body",
  },
];
const GUEST_PERKS = [
  // First, because "do I need a paid key?" is the question that stops a
  // visitor before the button: no, the assistant has a free daily allowance.
  "home.guest_perk_free",
  "home.guest_perk_import",
  "home.guest_perk_telegram",
  "home.guest_perk_watchlist",
];

/**
 * One slot of the grid, drawing its card only once the slot nears the
 * viewport. Until then a skeleton holds the room — a slot has to take room
 * to come into view at all, and `.hm-slot:empty` would hide one that took
 * none. The slot is the element watched, so a card that then renders nothing
 * still leaves it empty and collapsed, as before. `lead` is the control that
 * sits in the first slot's heading line, drawn whether or not the card is.
 */
function LazySlot({
  id,
  className,
  eager,
  lead,
  onSeen,
  children,
}: {
  id: CardId;
  className: string;
  eager: boolean;
  lead?: ReactNode;
  onSeen: (id: CardId) => void;
  children: ReactNode;
}) {
  const [ref, seen] = useInView<HTMLDivElement>(eager);
  useEffect(() => {
    if (seen) onSeen(id);
  }, [seen, id, onSeen]);
  return (
    <div ref={ref} className={className} data-card={id}>
      {lead}
      {seen ? children : <Skeleton rows={4} />}
    </div>
  );
}

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
  // The cards whose slots have come into view. A latch like the slots' own:
  // a card seen once keeps its figures while the reader scrolls on.
  const [seen, setSeen] = useState<ReadonlySet<CardId>>(() => new Set());
  const onSeen = useCallback((id: CardId) => {
    setSeen((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }, []);
  // On the page AND in view: a card put away in the editor after it was seen
  // stops asking.
  const wanted = (id: CardId) => shown.has(id) && seen.has(id);
  // One read behind the glance and the movers, and none until one of them is
  // in view.
  const book = useBook(nonce, !guest && (wanted("glance") || wanted("movers")));
  // Read here rather than in its card: the movers beside it match its rows.
  const extremes = useExtremes(nonce, wanted("extremes"));

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
        return <ExtremesCard query={extremes} book={book} />;
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
          below stays, its account-only steps locked, and its "don't show again"
          is not offered to a guest, who has no prefs to keep it in. */}
      {guest ? (
        <GuestBanner
          text="home.guest_banner"
          short="home.guest_banner_short"
          title="home.guest_title"
          dismissible="home"
          highlights={GUEST_HIGHLIGHTS}
          perks={GUEST_PERKS}
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
      ) : null}
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
              <LazySlot
                key={card.id}
                id={card.id}
                className={`hm-slot hm-slot-${card.span}${i === 0 ? " hm-slot-lead" : ""}`}
                eager={i === 0}
                lead={i === 0 ? customize : undefined}
                onSeen={onSeen}
              >
                {draw(card.id)}
              </LazySlot>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
