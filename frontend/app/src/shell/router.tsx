/**
 * The smallest router that serves this app, and no library for it.
 *
 * Every route is one path segment under the app's own base, and the only other
 * navigation state is the query string — deep links (`?ticker=AAPL`,
 * `?tab=fees`) that have to keep working, because those URLs are bookmarked
 * and shared.
 *
 * So: no nested routes, no params in the path, no history abstraction. Pushing
 * a URL and re-reading `location` is the whole model, and `popstate` makes the
 * back button work for free.
 */

import { useCallback, useEffect, useState, useTransition, type ReactNode } from "react";

import { canonical, preload } from "./pages";

/**
 * Where the app is mounted: the root. Kept here so nothing else hardcodes it.
 *
 * It was `/next` while the shell was being built; the server redirects that
 * prefix, and `/legacy`, to the same page here.
 */
export const BASE = "";

/**
 * Where `npm run dev` serves the document: under the bundle's own base, which
 * is not a page. Read past it so the dev server opens the page it was pointed
 * at instead of falling back to Home.
 */
const DEV_BASE = "/next-assets";

/** The page part of a pathname, whichever server served it. */
export function pagePath(pathname: string): string {
  const path = pathname.startsWith(DEV_BASE)
    ? pathname.slice(DEV_BASE.length)
    : pathname;
  return path.slice(BASE.length).replace(/^\/|\/$/g, "");
}

export type Route = { page: string; params: URLSearchParams };

/**
 * The page a URL means — which is not always the one its path names.
 *
 * `?ticker=SYM` on any page opens that ticker's page: the pre-refactor app
 * served every symbol at `/?ticker=`, and those links are in bookmarks, old
 * Telegram digests and shared chats. No other page
 * gives `ticker` a meaning of its own, so there is nothing for the jump to
 * shadow. Pure, so the rule can be tested without a location to read.
 */
export function routeFor(path: string, search: string): Route {
  const params = new URLSearchParams(search);
  // Canonical, not literal: a bookmark of a page's old path
  // (`/import_transactions`) has to light the same nav entry and load the
  // same chunk as the new one, rather than falling through to Home.
  const page = canonical(path || "home");
  if (page !== "ticker" && (params.get("ticker") ?? "").trim()) {
    return { page: "ticker", params };
  }
  return { page, params };
}

function read(): Route {
  const route = routeFor(pagePath(window.location.pathname), window.location.search);
  if (route.page === "ticker" && pagePath(window.location.pathname) !== "ticker") {
    // Rewrite the address bar too, so the rail lights Ticker, a reload lands
    // where the reader is, and the back button skips the page they never saw.
    window.history.replaceState(null, "", `${BASE}/ticker${window.location.search}`);
  }
  return route;
}

/**
 * Tell every `useRoute` that the URL moved.
 *
 * Each call site holds its own copy of the route, so a hook that only called
 * its own `setRoute` would move the address bar and leave every other
 * component reading the old URL — a page could write `?tour=1` and the shell's
 * tour, mounted beside it, would never hear about it. `popstate` is the
 * channel the back button already uses and that `Link` already fires, so
 * reusing it keeps one way for a navigation to propagate instead of two.
 */
function announce(): void {
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/**
 * How many in-app steps back the current entry is from where this visit
 * started. Kept in each entry's `history.state`, so it holds across back and
 * forward and a reload; the shell's back button needs it, because an app
 * opened from a home screen has no browser one.
 */
export function depth(): number {
  const state: unknown = typeof window === "undefined" ? null : window.history.state;
  const value = (state as { depth?: unknown } | null)?.depth;
  return typeof value === "number" ? value : 0;
}

/**
 * Where each visited address was scrolled to when the reader left it, so back
 * and forward land where they were. The browser's own restoration cannot: the
 * page is a lazy chunk that has not rendered, let alone fetched, by the time
 * `popstate` fires, so there is nothing tall enough to scroll to yet.
 */
const scrolls = new Map<string, number>();
let here = typeof window === "undefined" ? "" : place();
// Set by a `popstate` that moved to another address, or to the top by a
// `push`, and taken by the page once it has rendered (`takeRestore`): the
// scroll waits for the page, because the one on screen stays until then.
let restore: number | null = null;

function place(): string {
  const { pathname = "", search = "" } = window.location ?? {};
  return `${pathname}${search}`;
}

if (typeof window !== "undefined") {
  // Registered before any `useRoute`, so it sees the old page still scrolled
  // where the reader left it. `push` and `setParams` move `here` themselves,
  // which is how their own announcements are told apart from a real back.
  window.addEventListener("popstate", () => {
    const next = place();
    if (next === here) return;
    scrolls.set(here, window.scrollY);
    here = next;
    restore = scrolls.get(next) ?? null;
  });
}

/**
 * The scroll the page just rendered should land at, once: where a
 * back/forward step left this address, the top after a push, or null when
 * nothing asked for one (a tab switched in place).
 */
export function takeRestore(): number | null {
  const y = restore;
  restore = null;
  return y;
}

/** `pushState` to `href`, one step deeper than here. A fresh page starts at the top. */
export function push(href: string): void {
  scrolls.set(here, window.scrollY);
  restore = 0;
  window.history.pushState({ depth: depth() + 1 }, "", href);
  here = place();
}

/** What the address bar means now, as the page column keys its render. */
function at(): string {
  const route = routeFor(pagePath(window.location.pathname), window.location.search);
  return `${route.page}?${route.params}`;
}

/**
 * Push `href` and tell every `useRoute`. The next page scrolls to the top
 * itself once it has rendered (`takeRestore`), not here: the move is a
 * transition, so the page on screen stays until the next one's code is ready,
 * and scrolling it now would be a jump the reader did not ask for. The same
 * address again renders nothing new, so that one scrolls now.
 */
export function navigate(href: string): void {
  const from = at();
  push(href);
  announce();
  if (at() === from) {
    restore = null;
    window.scrollTo(0, 0);
  }
}

export function useRoute(): Route & {
  go: (page: string, params?: Record<string, string>) => void;
  setParams: (params: Record<string, string | undefined>) => void;
  /** A move is under way and the screen on show is still the last one. */
  pending: boolean;
} {
  const [route, setRoute] = useState<Route>(read);
  // A transition: the page on screen stays, interactive, until the next one
  // can render — its code arrived — instead of giving way to a skeleton
  // for the wait. `pending` is how the shell says the move is under way.
  const [pending, start] = useTransition();

  useEffect(() => {
    const onPop = () => start(() => setRoute(read()));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((page: string, params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    navigate(`${BASE}/${page}${query}`);
  }, []);

  /**
   * Change the query without adding a history entry.
   *
   * Switching a tab is not a navigation the back button should have to walk
   * back through: the tab is in the URL for a shareable link, not as a step
   * in history.
   */
  const setParams = useCallback((params: Record<string, string | undefined>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
    here = place();
    announce();
  }, []);

  return { ...route, go, setParams, pending };
}

/** A link that navigates in-app but is still a real href a reader can copy. */
export function Link({
  page,
  params,
  children,
  className,
  title,
  current,
  label,
}: {
  page: string;
  params?: Record<string, string>;
  children: ReactNode;
  className?: string;
  /** Hover text. A ticker cell needs it: the symbol alone is not the name. */
  title?: string;
  /** This link is the page the reader is on (`aria-current="page"`). */
  current?: boolean;
  /** The accessible name, where the visible text is hidden or clipped. */
  label?: string;
}) {
  const query = params ? `?${new URLSearchParams(params)}` : "";
  const href = `${BASE}/${page}${query}`;
  // The page's code is fetched on the first sign the reader may want it — the
  // pointer arriving, a press starting, focus landing — so the click itself
  // opens from the module cache. Idempotent and cheap once it has been.
  const warm = () => preload(page);
  return (
    <a
      className={className}
      href={href}
      title={title}
      aria-current={current ? "page" : undefined}
      aria-label={label}
      onPointerEnter={warm}
      onPointerDown={warm}
      onFocus={warm}
      onClick={(event) => {
        // Let the browser handle anything that is not a plain left click: a
        // middle click or ctrl-click means "open elsewhere", and swallowing it
        // is the thing that makes an SPA feel broken.
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey)
          return;
        if (event.button !== 0) return;
        event.preventDefault();
        navigate(href);
      }}
    >
      {children}
    </a>
  );
}
