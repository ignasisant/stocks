/**
 * The guest idiom, in one place.
 *
 * An anonymous visitor sees most of this app: the watchlist, the whole
 * Portfolio over a shared demo book, a ticker, a sector, the earnings calendar,
 * the market regime. What they do not see is anything that is *somebody's* —
 * favourites, tags, alerts, imports, the assistant, the profile — and every one
 * of those is hidden the same two ways, deliberately:
 *
 * - `<SignedInOnly>` where a block is **replaced**. Not rendering the child also
 *   cancels its fetch, because `useApi` fires from inside it — so a guest
 *   Home does not spend a request on a ledger it may not read.
 * - `useGuest()` where a **parent owns the query**. Home holds one ledger query
 *   that three children share, and no wrapper can un-fire a hook its parent
 *   already called. Same idiom as the conditional fetch in `Ticker.tsx`.
 *
 * Saying it once here rather than at each site is also what makes the i18n
 * parity check pass: `test_page_parity._said` scans `pages/<slug>` plus
 * `shell/`, so `common.sign_in_google` said once in this file closes the Home
 * and Portfolio waivers together.
 */

import { useState, type ReactNode } from "react";
import { useT } from "./i18n";
import { useGuest, useSignIn } from "./session";
import { BASE, pagePath } from "./router";

/**
 * Where the round trip should come back to: this document's own path.
 *
 * Always this origin. The sign-in is a server route on the API's origin, which
 * in production is this one — but under `npm run dev` the document is served by
 * Vite under its asset base, and that path on the API's origin is a static-file
 * route that 404s. So the dev base is translated back to where the shell really
 * lives before it is handed over as `next`.
 */
export function signInHref(target: string | null, here?: Location): string | null {
  if (!target) return null;
  const { pathname, search } = here ?? window.location;
  const page = pagePath(pathname);
  return `${target}?next=${encodeURIComponent(`${BASE}/${page}${search}`)}`;
}

/**
 * The sign-in button, wherever one is offered.
 *
 * Renders nothing when the deployment has no identity provider configured — a
 * button that sends somebody to a route which 404s is worse than no button, and
 * `/me` tells us which deployment this is precisely so the shell need not guess.
 */
export function SignIn({
  label,
  className = "ag-btn",
}: {
  label?: string;
  className?: string;
}) {
  const t = useT();
  const href = signInHref(useSignIn());
  if (!href) return null;
  return (
    <a className={className} href={href}>
      {t(label ?? "common.sign_in_google")}
    </a>
  );
}

/**
 * Render `children` for an account, `fallback` for a guest.
 *
 * The fallback defaults to nothing, because most of what a guest cannot have is
 * a control rather than a section — a star, a tag menu, an assistant button —
 * and the honest thing to show in a control's place is usually the space it
 * would have taken.
 */
export function SignedInOnly({
  children,
  fallback = null,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  return <>{useGuest() ? fallback : children}</>;
}

/**
 * The banner that says what this book is, at the top of a screen showing one.
 *
 * Two phrasings and both ship already — the long one names what a guest has,
 * the short one is for a screen whose own empty states say the rest. Streamlit
 * picks between them the same way; this is the same decision moved, not a new
 * one.
 */
/**
 * Whether a dismissible banner was put away in this tab.
 *
 * `sessionStorage`, because that is the lifetime Streamlit gives the same
 * button (`guest_banner_dismissed` in session state): a guest has no account to
 * remember a preference in, and the shared guest prefs.json is read-only — so
 * the banner comes back on the next visit, which is right for a line that is
 * the visitor's way to an account of their own.
 */
export function bannerDismissed(key: string, storage?: Storage | null): boolean {
  try {
    return (storage ?? window.sessionStorage).getItem(`bannerDismissed:${key}`) === "1";
  } catch {
    return false;
  }
}

export function dismissBanner(key: string, storage?: Storage | null): void {
  try {
    (storage ?? window.sessionStorage).setItem(`bannerDismissed:${key}`, "1");
  } catch {
    // The banner still goes for this render; it will just be back on reload.
  }
}

export function GuestBanner({
  text,
  short,
  dismissible,
  children,
}: {
  text: string;
  /**
   * The wording for a deployment with no identity provider.
   *
   * Both phrasings already ship, and `home.py` picks between them the same
   * way: the long one ends "sign in to build your own", which is a sentence
   * that must not be printed beside no button. This is that decision moved,
   * not a new one.
   */
  short?: string;
  /**
   * Offer "Dismiss", remembered for this tab under this key. Home's welcome
   * banner has one in Streamlit (`home.py`); the Portfolio's "these trades are
   * invented" deliberately does not — every figure under it is fiction, and
   * that is not a line to put away.
   */
  dismissible?: string;
  /** A second action beside the sign-in, where a page has one. */
  children?: ReactNode;
}) {
  const t = useT();
  const signIn = useSignIn();
  const [gone, setGone] = useState(() =>
    dismissible ? bannerDismissed(dismissible) : false,
  );
  if (gone) return null;
  return (
    <div className="ag-note ag-guest">
      <p>{t(signIn || !short ? text : short)}</p>
      <SignIn />
      {children}
      {dismissible ? (
        <button
          type="button"
          className="ag-guest-dismiss"
          onClick={() => {
            dismissBanner(dismissible);
            setGone(true);
          }}
        >
          {t("home.dismiss")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * What a guest gets where an account would see its own data.
 *
 * One component rather than a phrase repeated at eight sites, so that "sign in
 * to see yours" reads the same on every screen that says it.
 */
export function SignInWall({
  text,
  note,
  cta,
}: {
  text: string;
  /** The smaller line under it — what is missing, not why it is missing. */
  note?: string;
  /** A page's own wording for the button, where it has one. */
  cta?: string;
}) {
  const t = useT();
  return (
    <div className="ag-note ag-signin-wall">
      <p>{t(text)}</p>
      {note ? <p className="ag-help">{t(note)}</p> : null}
      <SignIn label={cta} />
    </div>
  );
}

/**
 * What of the shell's own chrome a guest gets, as a table rather than as `guest
 * &&` scattered through `Layout`.
 *
 * Mirrors what the Streamlit sidebar does for an anonymous visitor, which is
 * the specification for all of this: the rail and the search box are how a
 * visitor moves at all, feedback is offered to guests on purpose, the tour is
 * mounted but never opens itself at somebody who has not arrived anywhere yet
 * (`?tour=1` opens it, with the steps that read somebody's own data locked),
 * and the chat drawer spends the operator's API keys and writes a file every
 * visitor would share. The investor-profile nudge is an account's, and voice
 * dictation in feedback spends the transcription key a `Writer` route guards.
 */
export const GUEST_CHROME = {
  nav: true,
  search: true,
  feedback: true,
  /** Mounted, so `?tour=1` works — but it never opens itself for a guest. */
  tour: true,
  chat: false,
  profilePrompt: false,
  dictation: false,
} as const;
