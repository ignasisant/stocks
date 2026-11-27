/**
 * Home — the daily glance: the market, what's new, and the key portfolio
 * figures.
 *
 * The running order is the reader's. The page draws the cards in
 * `prefs.home_layout` (see `cards.ts`), and the default a new account gets is
 * the movers on top (every position, the full row), the market strip right
 * under them, then the 52-week extremes, the Portfolio page's headline metrics, the earnings
 * calendar, the recent transactions, the watchlist groups. Risk, dividends,
 * the tax year and sector rotation wait in the editor's tray. The AI daily
 * briefing is not a Home card: it lives on Today, one tab away. Every ticker
 * cell links to its own page; the full ledger analytics stay on Portfolio.
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
 * The start card opens the page, above the cards: a line of icons, each a
 * door into the section that switches it on, is the first thing a new account
 * needs and the last thing a settled one reads — which is why it is gone once
 * everything on it is done.
 *
 * Deliberately not here, because another pass owns them: the chat drawer and
 * the guided tour, both mounted by the shell.
 *
 * For a guest this page loses everything that is *somebody's* and keeps
 * everything that is the market's: no movers, no glance, no recent
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
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { get, invalidate, send } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useT } from "../../shell/i18n";
import { GuestBanner, SignInWall, type GuestHighlight } from "../../shell/guest";
import { useGuest, useSession } from "../../shell/session";
import { Skeleton } from "../../shell/Layout";
import {
  PageLoading,
  SkeletonWatch,
  useSkeletonWatch,
  type LoadingStep,
} from "../../shell/Loading";
import { Link } from "../../shell/router";
import { Icon } from "../../shell/Icon";
import { useInView } from "../../shell/useInView";
import { SetupCard } from "./Setup";
import { TourOffer } from "./TourOffer";
import { Glance, MoversSlot, useBook } from "./Glance";
import { useLiveDay } from "./liveDay";
import { MarketCard } from "./Market";
import { EarningsCard } from "./Earnings";
import { RecentTransactions } from "./Transactions";
import { ExtremesCard, useExtremes } from "./Extremes";
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
  "home.guest_perk_notify",
  "home.guest_perk_watchlist",
];

/** Where one block of the page stands: what it still waits for (null once
 * nothing in it is a skeleton), and whether it drew anything at all. */
/** `fold`: the block starts within the first screen, where a reader looks. */
type BlockState = { waiting: string | null; content: boolean; fold: boolean };

const sameState = (a: BlockState | undefined, b: BlockState): boolean =>
  a !== undefined &&
  a.waiting === b.waiting &&
  a.content === b.content &&
  a.fold === b.fold;

/**
 * Watch the skeletons drawn inside a block and report where it stands, before
 * paint — so the page can tell "everything still loading" from "something to
 * show" on the very frame it draws. `ready` false (a slot not yet in view)
 * reports nothing landed whatever is in it.
 */
function useBlockState(
  id: string,
  ready: boolean,
  onState: (id: string, state: BlockState) => void,
): {
  watch: (kind: string) => () => void;
  box: React.RefObject<HTMLDivElement | null>;
} {
  const { watch, waiting } = useSkeletonWatch();
  const box = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    // The DOM is the truth for whether a skeleton is up: on the frame one
    // mounts, its registration has not re-rendered this block yet, and
    // `waiting` alone would call the slot landed for that one pass.
    const skeleton = el?.querySelector(".ag-skeleton") != null;
    // Anything but the "Customise" control the lead slot carries.
    const drawn =
      el != null &&
      [...el.children].some((child) => !child.classList.contains("hm-customize"));
    const still = waiting ?? (skeleton ? "activity.other" : null);
    onState(id, {
      waiting: ready ? still : "activity.other",
      content: ready && still === null && drawn,
      fold: el != null && el.getBoundingClientRect().top < window.innerHeight,
    });
  }, [id, ready, waiting, onState]);
  return { watch, box };
}

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
  onState,
  children,
}: {
  id: CardId;
  className: string;
  eager: boolean;
  lead?: ReactNode;
  onSeen: (id: CardId) => void;
  onState: (id: string, state: BlockState) => void;
  children: ReactNode;
}) {
  const [ref, seen] = useInView<HTMLDivElement>(eager);
  const { watch, box } = useBlockState(id, seen, onState);
  const attach = useCallback(
    (node: HTMLDivElement | null) => {
      box.current = node;
      ref(node);
    },
    [box, ref],
  );
  useEffect(() => {
    if (seen) onSeen(id);
  }, [seen, id, onSeen]);
  return (
    <div ref={attach} className={className} data-card={id}>
      {lead}
      <SkeletonWatch.Provider value={watch}>
        {seen ? children : <Skeleton rows={4} />}
      </SkeletonWatch.Provider>
    </div>
  );
}

/** The start card, watched like a slot: a new account's checklist is
 * something to show. `display: contents`, so it lays out as it always did. */
function WatchedSetup({
  onState,
}: {
  onState: (id: string, state: BlockState) => void;
}) {
  const { watch, box } = useBlockState("setup", true, onState);
  return (
    <div ref={box} className="hm-watch">
      <SkeletonWatch.Provider value={watch}>
        <SetupCard />
      </SkeletonWatch.Provider>
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
  // guest may not write, so a guest's press drops this page's memo and
  // re-asks — which still picks up anything whose short TTL has rolled over.
  // A refused or failed drop is not worth an error: the re-ask happens
  // either way.
  const refresh = useCallback(() => {
    const drop = guest
      ? Promise.resolve(invalidate())
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
  const onPage = new Set<CardId>(cards.map((card) => card.id));
  // The cards whose slots have come into view. A latch like the slots' own:
  // a card seen once keeps its figures while the reader scrolls on.
  const [seen, setSeen] = useState<ReadonlySet<CardId>>(() => new Set());
  const onSeen = useCallback((id: CardId) => {
    setSeen((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }, []);
  // On the page AND in view: a card put away in the editor after it was seen
  // stops asking.
  const wanted = (id: CardId) => onPage.has(id) && seen.has(id);
  // One read behind the glance and the movers, and none until one of them is
  // in view.
  // The day then kept live while a held name trades (`useLiveDay`).
  const book = useLiveDay(
    useBook(nonce, !guest && (wanted("glance") || wanted("movers"))),
  );
  // Read here, like the book, so a refresh's nonce reaches it.
  const extremes = useExtremes(nonce, wanted("extremes"));

  // While no block in view has anything to show, one card stands in for the
  // page (`PageLoading`) instead of a column of captioned grey bars; the
  // grid loads behind it, hidden, and is shown as is the moment one card
  // lands — or every one in view turns out to have nothing to say. Once
  // shown it stays shown: a refresh re-asking is not a page loading.
  const [blocks, setBlocks] = useState<Readonly<Record<string, BlockState>>>({});
  const onState = useCallback((id: string, state: BlockState) => {
    setBlocks((prev) => (sameState(prev[id], state) ? prev : { ...prev, [id]: state }));
  }, []);
  const inView = cards.filter((card) => seen.has(card.id));
  const watched = [...inView.map((card) => blocks[card.id]), blocks.setup];
  const firstScreen = watched.filter((state) => state?.fold === true) as BlockState[];
  const landed =
    editing ||
    cards.length === 0 ||
    // Something to read on the first screen: a card that lands further down
    // would open on a screen of skeletons.
    watched.some((state) => state?.content && state.fold) ||
    (inView.length > 0 && watched.every((state) => state && state.waiting === null)) ||
    (firstScreen.length > 0 &&
      firstScreen.every((state) => state.waiting === null) &&
      watched.some((state) => state?.content));
  const [shown, setShown] = useState(false);
  useLayoutEffect(() => {
    if (landed) setShown(true);
  }, [landed]);
  const waiting = !shown && !landed;
  // The page fades in only after the loading card stood in for it; a Home
  // that answers at once just appears.
  const [waited, setWaited] = useState(false);
  useLayoutEffect(() => {
    if (waiting) setWaited(true);
  }, [waiting]);
  const steps: LoadingStep[] = inView.map((card) => ({
    id: card.id,
    label: t(`home.card_${card.id}`),
    waiting: blocks[card.id]?.waiting ?? "activity.other",
  }));

  const draw = (id: CardId): ReactNode => {
    switch (id) {
      case "market":
        return <MarketCard nonce={nonce} />;
      case "glance":
        return <Glance query={book} ledger={ledger} />;
      case "movers":
        return <MoversSlot query={book} alone={!onPage.has("glance")} />;
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
      {/* Every other page opens on its title; Home has none on screen, so a
          screen reader's heading list would start at a card. */}
      <h1 className="ag-sr">{t("nav.home")}</h1>
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
      <TourOffer />
      <div
        className="hm-wait"
        data-waiting={waiting || undefined}
        data-revealed={(waited && !waiting) || undefined}
      >
        {waiting ? <PageLoading title={t("home.loading_title")} steps={steps} /> : null}
        <div className="hm-wait-body">
          <WatchedSetup onState={onState} />
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
                    onState={onState}
                  >
                    {draw(card.id)}
                  </LazySlot>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
