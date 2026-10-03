/**
 * The chrome every page sits in: the nav rail, and the states a page can be in
 * before it has anything to show.
 *
 * The four states are the shell's job and not each page's. A page that hand-
 * rolls its own is a page that will eventually render a spinner forever, or a
 * zero where a number could not be fetched — which is the failure this whole
 * API was built to make impossible.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
// The mark the landing and the favicon already draw (`web/assets/`),
// imported rather than copied into this app: two files would be one logo only
// until somebody changed one of them. Vite hashes it into the build and emits
// it beside the bundle; `vite.config.ts` grants the dev server the read.
import logoUrl from "../../../../src/stocks/web/assets/topstocks-icon.svg?url";
import { Drawer } from "../chat/Drawer";
import { useT } from "./i18n";
import { Feedback } from "./Feedback";
import { Search } from "./Search";
import { ProfilePrompt } from "./ProfilePrompt";
import { Tour } from "./Tour";
import { Link, useRoute } from "./router";
import { BOTTOM, PAGES, sections } from "./pages";
import "./shell.css";
import { isTransient } from "./api";
import { Icon } from "./Icon";
import { GUEST_CHROME, SignIn } from "./guest";
import { useBank, useGuest } from "./session";
import type { Query } from "./useApi";
import { useStaleSince } from "./freshness";
import { useActivity } from "./activity";

/**
 * Whether the rail is folded to its icons, remembered per browser.
 *
 * Browser storage rather than `/prefs`: which one of two chromes a screen
 * shows is a property of the screen, not of the account — the same book read
 * on a laptop beside an editor and on a wide monitor wants different answers,
 * and a preference would make the second one overwrite the first. Read once,
 * synchronously, so the rail never paints open and then folds.
 */
const FOLDED = "navFolded";

function storedFold(): boolean {
  try {
    return window.localStorage.getItem(FOLDED) === "1";
  } catch {
    // Private windows and blocked site data throw on the read itself. An
    // unfolded rail is the right thing to show when nobody can say otherwise.
    return false;
  }
}

/** How long the peeked rail takes to fold away — the `.ag-nav` clip-path
 *  transition under `[data-nav="peek-out"]` in styles.css. */
const PEEK_OUT_MS = 160;

function Nav() {
  const t = useT();
  const { page } = useRoute();
  const guest = useGuest();
  const [folded, setFolded] = useState(storedFold);
  // The phone bar's "More" sheet. Closed by any move, so it never outlives the
  // page it was opened over.
  const [more, setMore] = useState(false);
  useEffect(() => setMore(false), [page]);

  // Folded, a pointer resting on the rail unfolds it over the page — labels and
  // all — and leaving folds it back. Over, not beside: the grid column keeps
  // its icon width, so the page never reflows under a cursor that was only
  // passing through. The fold control is what makes it stay.
  // "out" is the fold back: the rail keeps its open width while the reveal
  // runs in reverse (`PEEK_OUT_MS`, styles.css), then drops to the column.
  const [peek, setPeek] = useState<"off" | "on" | "out">("off");
  // A rail folded by its own button is still under the pointer that pressed
  // it; peeking straight back open would make the press look ignored. Held off
  // until the pointer leaves.
  const held = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const peekRef = useRef(peek);
  peekRef.current = peek;
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const fold = useCallback((next: boolean) => {
    setFolded(next);
    window.clearTimeout(timer.current);
    setPeek("off");
    held.current = next;
    try {
      window.localStorage.setItem(FOLDED, next ? "1" : "0");
    } catch {
      // The rail has already moved; a preference that could not be written is
      // worth exactly one lost reload.
    }
  }, []);

  const enter = useCallback(() => {
    // Touch screens fire a synthetic enter on every tap; only a real hover
    // pointer peeks. The phone bar never does either way (see styles.css).
    if (held.current || !window.matchMedia?.("(hover: hover)").matches) return;
    window.clearTimeout(timer.current);
    // Back in while it is still folding away: reopen from where it is (the
    // transition retargets) rather than waiting out the delay again.
    if (peekRef.current === "out") return setPeek("on");
    // A beat before opening, so a cursor crossing to the page's left edge
    // does not flash the rail open on its way past.
    timer.current = window.setTimeout(() => setPeek("on"), 120);
  }, []);

  const leave = useCallback(() => {
    held.current = false;
    window.clearTimeout(timer.current);
    // Reduced motion has no fold-away to wait out (styles.css drops it).
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (peekRef.current !== "on" || still) return setPeek("off");
    setPeek("out");
    timer.current = window.setTimeout(() => setPeek("off"), PEEK_OUT_MS);
  }, []);

  // The rail's width is the shell's grid column, not the rail's own property,
  // so the state has to reach an ancestor. The document element rather than a
  // class on `.ag-shell`, which `Layout` renders and this component does not.
  // "peek" keeps the folded column and draws the open rail over it.
  useEffect(() => {
    document.documentElement.dataset.nav = !folded
      ? "open"
      : peek === "on"
        ? "peek"
        : peek === "out"
          ? "peek-out"
          : "folded";
  }, [folded, peek]);

  const label = t(folded ? "nav.expand" : "nav.collapse");
  // Grouped under the menu's headers (`stocks.navigation.sections`): Home on
  // its own, then Portfolio, Market and Account. Bank joins the Account group
  // only for a reader `/me` says is on its allowlist — for everyone else the
  // page stays reachable by URL and absent from the rail.
  const groups = sections(PAGES, useBank() ? ["bank"] : []);
  return (
    <nav
      className="ag-nav"
      aria-label={t("nav.sections")}
      onMouseEnter={folded ? enter : undefined}
      onMouseLeave={folded ? leave : undefined}
    >
      {/* The brand, and the control that folds the rail under it. Neither
          belongs on a phone, where the rail is the bottom tab bar and the
          page header already carries the mark — `ag-nav-brand` is hidden
          below 640px, as the labels are. */}
      <div className="ag-nav-brand">
        <img className="ag-nav-mark" src={logoUrl} alt="" width={24} height={24} />
        <span className="ag-nav-wordmark">TopStocks</span>
        <button
          type="button"
          className="ag-nav-fold"
          onClick={() => fold(!folded)}
          title={label}
          aria-label={label}
          aria-expanded={!folded}
        >
          <Icon name="menu" />
        </button>
      </div>
      {groups.map((group) => (
        <div className="ag-nav-group" key={group.section ?? "top"}>
          {group.section ? (
            // A header, not a link: it names the group for a reader scanning
            // the rail, and it is hidden where there is no room for words
            // (folded, and on the phone bar).
            <span className="ag-nav-section">{t(group.section)}</span>
          ) : null}
          {group.pages.map((entry) => (
            <Link
              key={entry.slug}
              page={entry.slug}
              className={[
                "ag-nav-item",
                entry.slug === page ? "ag-nav-on" : "",
                BOTTOM.includes(entry.slug) ? "" : "ag-nav-extra",
              ]
                .filter(Boolean)
                .join(" ")}
              // Folded, the glyph is all there is: without this the rail
              // becomes nine unnamed icons for a pointer as well as a reader.
              title={folded && peek === "off" ? t(entry.label) : undefined}
              // The label is hidden on a phone's bar, and a hidden label names
              // nothing: this is what a reader hears there.
              aria-label={t(entry.label)}
            >
              <Icon name={entry.icon} />
              <span className="ag-nav-label">{t(entry.label)}</span>
            </Link>
          ))}
        </div>
      ))}
      {/* Foot of the rail: reachable from every page, in the way of none of
          them. Feedback is offered to guests as well — a visitor who bounced
          telling us why is worth more than a login, which is why the API keeps
          one unauthenticated write. The sign-in is the one thing the rail
          gains for a guest: the way out of the demo. On a phone both move
          into the "More" sheet. */}
      <div className="ag-nav-foot">
        {!guest || GUEST_CHROME.feedback ? <Feedback /> : null}
        {guest ? <SignIn className="ag-btn ag-nav-signin" /> : null}
      </div>
      {/* Phones only: the bar holds `BOTTOM`, and this is the way to the rest
          — the drawer the DS spec keeps behind the bar. */}
      <button
        type="button"
        className={
          more ? "ag-nav-item ag-nav-more ag-nav-on" : "ag-nav-item ag-nav-more"
        }
        onClick={() => setMore(!more)}
        aria-expanded={more}
        aria-label={t("nav.more")}
      >
        <Icon name="menu" />
        <span className="ag-nav-label">{t("nav.more")}</span>
      </button>
      {more ? (
        <>
          <div
            className="ag-nav-scrim"
            role="presentation"
            onClick={() => setMore(false)}
          />
          <div className="ag-nav-sheet">
            {groups.map((group) => {
              const extra = group.pages.filter((entry) => !BOTTOM.includes(entry.slug));
              if (!extra.length) return null;
              return (
                <div className="ag-nav-group" key={group.section ?? "top"}>
                  {group.section ? (
                    <span className="ag-nav-section">{t(group.section)}</span>
                  ) : null}
                  {extra.map((entry) => (
                    <Link
                      key={entry.slug}
                      page={entry.slug}
                      className={
                        entry.slug === page ? "ag-nav-item ag-nav-on" : "ag-nav-item"
                      }
                    >
                      <Icon name={entry.icon} />
                      <span>{t(entry.label)}</span>
                    </Link>
                  ))}
                </div>
              );
            })}
            {!guest || GUEST_CHROME.feedback ? <Feedback /> : null}
            {guest ? <SignIn className="ag-btn" /> : null}
          </div>
        </>
      ) : null}
    </nav>
  );
}

/**
 * One line, on every page, whenever a figure on it is older than it looks.
 *
 * The API says so per response (`X-Data-Stale-Since`) when the price source
 * refused and the last good data stood in; this reads the oldest such mark and
 * goes away on its own once a live answer replaces it. Here rather than in each
 * card because the same download feeds half the cards on a screen, and one
 * sentence beats six badges saying the same thing.
 */
function StaleNotice() {
  const t = useT();
  const since = useStaleSince();
  if (since === null) return null;
  const when = new Date(since).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (
    <p className="ag-stale" role="status">
      {t("common.stale_notice", { when })}
    </p>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const guest = useGuest();
  return (
    <div className="ag-shell">
      <Nav />
      <main className="ag-main">
        {/* Above the page rather than in a bar of its own: the rail is this
            app's only chrome, and a second horizontal band would cost a phone
            the height the page needs. Both of these are on every screen, which
            is the whole reason they live out here. */}
        <Search />
        <StaleNotice />
        {/* Inside the page column, above the body: when the tour is parked
            this is where its strip sits, on every page. The modal itself is
            fixed-position, so where it mounts does not move it. Mounted for
            guests too — `?tour=1` opens it for them — but it never opens
            itself at somebody who has not arrived anywhere yet. */}
        {!guest || GUEST_CHROME.tour ? <Tour /> : null}
        {children}
      </main>
      {/* What a guest does not get, read off one table rather than out of the
          JSX: the assistant spends the operator's API keys and writes a
          `chat.json` every anonymous visitor would share, and the profile
          nudge is about an account a guest does not have. */}
      {!guest || GUEST_CHROME.chat ? <Drawer /> : null}
      {!guest || GUEST_CHROME.profilePrompt ? <ProfilePrompt /> : null}
      <ActivityBanner />
    </div>
  );
}

/**
 * The corner banner: what is taking a while, and how far along the page is.
 *
 * Silent until a request has been out for `activity.SLOW_MS` — a page that
 * answers promptly never shows it. Bottom-left on a phone would sit on the tab
 * bar, so it is bottom-right everywhere, above the assistant's button.
 */
function ActivityBanner() {
  const t = useT();
  const { slow, done, total } = useActivity();
  if (slow.length === 0) return null;
  const share = total ? Math.min(1, done / total) : 0;
  return (
    <div className="ag-activity" role="status" aria-live="polite">
      <div className="ag-activity-head">
        <span className="ag-activity-title">{t("activity.title")}</span>
        <span className="ag-activity-count">
          {t("activity.progress", { done, total })}
        </span>
      </div>
      <ul className="ag-activity-list">
        {slow.slice(0, 3).map((kind) => (
          <li key={kind}>{t(kind)}</li>
        ))}
      </ul>
      <div className="ag-activity-bar" aria-hidden="true">
        <div style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
    </div>
  );
}

/**
 * One figure that is still on its way, in the cell it will land in.
 *
 * For tables whose rows are already known — the tickers a reader holds, the
 * names on their list — and whose prices are not: the row draws at once and
 * only the cell that is waiting shimmers. A figure that *could not* be fetched
 * is a different fact and still reads "n/a".
 */
export function Pending() {
  const t = useT();
  return <span className="ag-pending" role="img" aria-label={t("common.loading")} />;
}

/**
 * A block of the page that is still loading — the shape of what is coming.
 *
 * A status with the word in it, not a hidden shape: the grey bars are all a
 * sighted reader needs, and without the word a screen reader hears nothing
 * where the block will land.
 */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  const t = useT();
  return (
    <div className="ag-skeleton" role="status">
      <span className="ag-sr">{t("common.loading")}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div className="ag-skeleton-row" key={i} />
      ))}
    </div>
  );
}

/**
 * Render a query's four states once, so no page has to.
 *
 * A transient failure — the upstream throttled us, or this client asked too
 * fast — says so and offers a retry. Anything else is a defect and reads like
 * one rather than hiding behind "try again".
 */
export function Loaded<T>({
  query,
  skeleton,
  children,
}: {
  query: Query<T>;
  skeleton?: ReactNode;
  children: (data: T, reload: () => void) => ReactNode;
}) {
  const t = useT();
  if (query.state === "loading") return <>{skeleton ?? <Skeleton />}</>;
  if (query.state === "signed-out")
    return <p className="ag-note">{t("common.sign_in")}</p>;
  if (query.state === "failed") {
    return (
      <div className="ag-note">
        <p>
          {t(isTransient(query.error) ? "common.data_unavailable" : "common.failed")}
        </p>
        <button className="ag-btn" onClick={query.retry}>
          {t("common.retry")}
        </button>
      </div>
    );
  }
  return <>{children(query.data, query.reload)}</>;
}
