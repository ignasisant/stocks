/**
 * The chrome every page sits in: the nav rail, and the states a page can be in
 * before it has anything to show.
 *
 * The four states are the shell's job and not each page's. A page that hand-
 * rolls its own is a page that will eventually render a spinner forever, or a
 * zero where a number could not be fetched — which is the failure this whole
 * API was built to make impossible.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
// The mark the Streamlit app and the landing already draw (`web/assets/`),
// imported rather than copied into this app: two files would be one logo only
// until somebody changed one of them. Vite hashes it into the build and emits
// it beside the bundle; `vite.config.ts` grants the dev server the read.
import logoUrl from "../../../../src/stocks/web/assets/topstocks-icon.svg?url";
import { Drawer } from "../chat/Drawer";
import { useT } from "./i18n";
import { Feedback } from "./Feedback";
import { Search } from "./Search";
import { Tour } from "./Tour";
import { Link, useRoute } from "./router";
import { PAGES } from "./pages";
import { isTransient } from "./api";
import { Icon } from "./Icon";
import { GUEST_CHROME, SignIn } from "./guest";
import { useGuest } from "./session";
import type { Query } from "./useApi";

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

function Nav() {
  const t = useT();
  const { page } = useRoute();
  const guest = useGuest();
  const [folded, setFolded] = useState(storedFold);

  const fold = useCallback((next: boolean) => {
    setFolded(next);
    try {
      window.localStorage.setItem(FOLDED, next ? "1" : "0");
    } catch {
      // The rail has already moved; a preference that could not be written is
      // worth exactly one lost reload.
    }
  }, []);

  // The rail's width is the shell's grid column, not the rail's own property,
  // so the state has to reach an ancestor. The document element rather than a
  // class on `.ag-shell`, which `Layout` renders and this component does not.
  useEffect(() => {
    document.documentElement.dataset.nav = folded ? "folded" : "open";
  }, [folded]);

  const label = t(folded ? "nav.expand" : "nav.collapse");
  return (
    <nav className="ag-nav" aria-label={t("nav.sections")}>
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
      {PAGES.filter((entry) => !entry.hidden).map((entry) => (
        <Link
          key={entry.slug}
          page={entry.slug}
          className={entry.slug === page ? "ag-nav-item ag-nav-on" : "ag-nav-item"}
          // Folded, the glyph is all there is: without this the rail becomes
          // eight unnamed icons for a pointer as well as for a reader.
          title={folded ? t(entry.label) : undefined}
        >
          <Icon name={entry.icon} />
          <span className="ag-nav-label">{t(entry.label)}</span>
        </Link>
      ))}
      {/* Foot of the rail, where the Streamlit sidebar puts it: reachable from
          every page, in the way of none of them. Feedback is offered to guests
          as well — a visitor who bounced telling us why is worth more than a
          login, which is why the API keeps one unauthenticated write. */}
      {!guest || GUEST_CHROME.feedback ? <Feedback /> : null}
      {/* The one thing the rail gains for a guest rather than loses: the way
          out of the demo. At the foot, where it is reachable from every screen
          without being the first thing on any of them. */}
      {guest ? <SignIn className="ag-btn ag-nav-signin" /> : null}
    </nav>
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
            the height the page needs. Both of these are on every screen in the
            Streamlit app too, which is the whole reason they live out here. */}
        <Search />
        {children}
      </main>
      {/* What a guest does not get, read off one table rather than out of the
          JSX: the assistant spends the operator's API keys and writes a
          `chat.json` every anonymous visitor would share, and the tour is a
          per-account place in a sequence — stamping it seen would hand the next
          visitor this one's progress through it. */}
      {!guest || GUEST_CHROME.chat ? <Drawer /> : null}
      {/* Last, and on top of everything: it interrupts on purpose — which is
          exactly why it does not interrupt somebody who has not arrived
          anywhere yet. */}
      {!guest || GUEST_CHROME.tour ? <Tour /> : null}
    </div>
  );
}

/** A block of the page that is still loading — the shape of what is coming. */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="ag-skeleton" aria-hidden="true">
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
