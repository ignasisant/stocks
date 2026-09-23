/**
 * The smallest router that serves this app, and no library for it.
 *
 * Every route is one path segment under the app's own base, and the only other
 * navigation state is the query string — which the Streamlit pages already use
 * for deep links (`?ticker=AAPL`, `?tab=fees`) and which has to keep working,
 * because those URLs are bookmarked and shared.
 *
 * So: no nested routes, no params in the path, no history abstraction. Pushing
 * a URL and re-reading `location` is the whole model, and `popstate` makes the
 * back button work for free.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { canonical } from "./pages";

/**
 * Where the app is mounted. Kept here so nothing else hardcodes it.
 *
 * Not `/app`: the logo mirror already serves `/app/static/`, and a shell that
 * claimed the whole prefix would take it. `/next` says what this is — the
 * rebuild, running beside the Streamlit app rather than over it — and leaves
 * every existing URL answering exactly as it does today.
 */
export const BASE = "/next";

export type Route = { page: string; params: URLSearchParams };

function read(): Route {
  const path = window.location.pathname.slice(BASE.length).replace(/^\/|\/$/g, "");
  return {
    // Canonical, not literal: a bookmark of the Streamlit URL this page
    // replaced (`/import_transactions`) has to light the same nav entry and
    // load the same chunk as the new one, rather than falling through to Home.
    page: canonical(path || "home"),
    params: new URLSearchParams(window.location.search),
  };
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

export function useRoute(): Route & {
  go: (page: string, params?: Record<string, string>) => void;
  setParams: (params: Record<string, string | undefined>) => void;
} {
  const [route, setRoute] = useState<Route>(read);

  useEffect(() => {
    const onPop = () => setRoute(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((page: string, params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    window.history.pushState(null, "", `${BASE}/${page}${query}`);
    announce();
    window.scrollTo(0, 0);
  }, []);

  /**
   * Change the query without adding a history entry.
   *
   * Switching a tab is not a navigation the back button should have to walk
   * back through — the Streamlit pages write the tab to the URL for the same
   * reason (a shareable link) and do not stack history for it either.
   */
  const setParams = useCallback((params: Record<string, string | undefined>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
    announce();
  }, []);

  return { ...route, go, setParams };
}

/** A link that navigates in-app but is still a real href a reader can copy. */
export function Link({
  page,
  params,
  children,
  className,
  title,
}: {
  page: string;
  params?: Record<string, string>;
  children: ReactNode;
  className?: string;
  /** Hover text. A ticker cell needs it: the symbol alone is not the name. */
  title?: string;
}) {
  const query = params ? `?${new URLSearchParams(params)}` : "";
  const href = `${BASE}/${page}${query}`;
  return (
    <a
      className={className}
      href={href}
      title={title}
      onClick={(event) => {
        // Let the browser handle anything that is not a plain left click: a
        // middle click or ctrl-click means "open elsewhere", and swallowing it
        // is the thing that makes an SPA feel broken.
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey)
          return;
        if (event.button !== 0) return;
        event.preventDefault();
        window.history.pushState(null, "", href);
        window.dispatchEvent(new PopStateEvent("popstate"));
        window.scrollTo(0, 0);
      }}
    >
      {children}
    </a>
  );
}
