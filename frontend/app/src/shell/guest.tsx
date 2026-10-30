/**
 * The guest idiom, in one place.
 *
 * An anonymous visitor sees most of this app: the watchlist, the whole
 * Portfolio over a shared demo book, a ticker, a sector, the earnings calendar,
 * the market regime. What they do not see is anything that is *somebody's* —
 * favourites, tags, alerts, imports, the assistant's answers, the profile — and every one
 * of those is hidden the same two ways, deliberately:
 *
 * - `<SignedInOnly>` where a block is **replaced**. Not rendering the child also
 *   cancels its fetch, because `useApi` fires from inside it — so a guest
 *   Home does not spend a request on a ledger it may not read.
 * - `useGuest()` where a **parent owns the query**. Home holds one ledger query
 *   that three children share, and no wrapper can un-fire a hook its parent
 *   already called. Same idiom as the conditional fetch in `Ticker.tsx`.
 */

import { useState, type ReactNode } from "react";
import { useLang, useT } from "./i18n";
import { useGuest, useSignIn } from "./session";
import { BASE, pagePath } from "./router";
import { Icon } from "./Icon";

/**
 * Where the round trip should come back to: this document's own path.
 *
 * Always this origin. The sign-in is a server route on the API's origin, which
 * in production is this one — but under `npm run dev` the document is served by
 * Vite under its asset base, and that path on the API's origin is a static-file
 * route that 404s. So the dev base is translated back to where the shell really
 * lives before it is handed over as `next`.
 *
 * `wall` names the prompt that was pressed, so the signup it leads to can say
 * which one converts (`auth.signup wall=`, `stocks logs funnel`). It defaults
 * to the page — a banner or a sign-in wall is the page's own prompt — and is
 * named outright where the button belongs to the shell rather than the page:
 * the rail, the tour, the locked assistant.
 */
export function signInHref(
  target: string | null,
  here?: Location,
  wall?: string,
): string | null {
  if (!target) return null;
  const { pathname, search } = here ?? window.location;
  const page = pagePath(pathname);
  const from = wall || page.split("/")[0] || "home";
  return (
    `${target}?next=${encodeURIComponent(`${BASE}/${page}${search}`)}` +
    `&wall=${encodeURIComponent(from)}`
  );
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
  wall,
}: {
  label?: string;
  className?: string;
  /** Which prompt this is, where it is not the page's own (`signInHref`). */
  wall?: string;
}) {
  const t = useT();
  const href = signInHref(useSignIn(), undefined, wall);
  if (!href) return null;
  return (
    <a className={className} href={href}>
      {t(label ?? "common.sign_in_google")}
    </a>
  );
}

/** A legal page in the reader's language; the server knows only en and es. */
export function legalHref(doc: "privacy" | "terms", lang: string): string {
  return `/legal/${doc}?lang=${lang.startsWith("es") ? "es" : "en"}`;
}

/**
 * What the Google round trip asks for and where the data goes, said before the
 * redirect: a visitor without a Google account learns the demo needs none, and
 * one with an account sees the two legal pages before handing anything over.
 * Nothing without a sign-in to offer, like the button it sits under.
 */
function SignInNote() {
  const t = useT();
  const lang = useLang();
  if (!useSignIn()) return null;
  return (
    <p className="ag-signin-note">
      {t("common.sign_in_note")}{" "}
      <a href={legalHref("privacy", lang)}>{t("common.privacy")}</a>
      {" · "}
      <a href={legalHref("terms", lang)}>{t("common.terms")}</a>
    </p>
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
 * the short one is for a screen whose own empty states say the rest.
 */
/**
 * Whether a dismissible banner was put away in this tab.
 *
 * `sessionStorage`, because a guest has no account to remember a preference
 * in, and the shared guest prefs.json is read-only — so the banner comes back
 * on the next visit, which is right for a line that is the visitor's way to an
 * account of their own.
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

/** One thing an account adds, as a card: a glyph, a name, one line of why. */
export type GuestHighlight = { icon: string; title: string; body: string };

export function GuestBanner({
  text,
  short,
  title,
  dismissible,
  highlights,
  perks,
  children,
}: {
  text: string;
  /**
   * The wording for a deployment with no identity provider.
   *
   * The long one ends "sign in to build your own", which is a sentence that
   * must not be printed beside no button.
   */
  short?: string;
  /** A headline over `text`, where the banner is a pitch rather than a note. */
  title?: string;
  /**
   * Offer "Dismiss", remembered for this tab under this key. Home's welcome
   * banner has one; the Portfolio's "these trades are invented" deliberately
   * does not — every figure under it is fiction, and that is not a line to
   * put away.
   */
  dismissible?: string;
  /**
   * What an account adds, worth a card each — the reason to sign in, read
   * before the button rather than after it.
   */
  highlights?: GuestHighlight[];
  /** The lesser gains, one ticked line under the cards. */
  perks?: string[];
  /** A second action beside the sign-in, where a page has one. */
  children?: ReactNode;
}) {
  const t = useT();
  const signIn = useSignIn();
  const [gone, setGone] = useState(() =>
    dismissible ? bannerDismissed(dismissible) : false,
  );
  if (gone) return null;
  // The pitch — headline, cards, ticks — only with a sign-in to offer: a list
  // of what you would get is a tease beside no way to get it.
  const pitch = Boolean(signIn);
  return (
    <section className="ag-note ag-guest">
      <div className="ag-guest-head">
        <span className="ag-guest-mark">
          <Icon name={pitch && title ? "auto_awesome" : "account_circle"} size={20} />
        </span>
        <div className="ag-guest-copy">
          {pitch && title ? <h2 className="ag-guest-title">{t(title)}</h2> : null}
          <p>{t(signIn || !short ? text : short)}</p>
        </div>
        <div className="ag-guest-actions">
          {/* The one filled button on the screen: the banner exists to get a
              visitor an account, so the way to one outranks every other action. */}
          <SignIn className="ag-btn ag-btn-cta" />
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
      </div>
      {pitch && highlights?.length ? (
        <ul className="ag-guest-highlights">
          {highlights.map((h) => (
            <li key={h.title}>
              <span className="ag-guest-highlight-icon">
                <Icon name={h.icon} size={18} />
              </span>
              <div>
                <strong>{t(h.title)}</strong>
                <p>{t(h.body)}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {pitch && perks?.length ? (
        <ul className="ag-guest-perks">
          {perks.map((key) => (
            <li key={key}>
              <Icon name="check" size={16} />
              {t(key)}
            </li>
          ))}
        </ul>
      ) : null}
      {pitch ? <SignInNote /> : null}
    </section>
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
      <SignInNote />
    </div>
  );
}

/**
 * What of the shell's own chrome a guest gets, as a table rather than as `guest
 * &&` scattered through `Layout`.
 *
 * The rail and the search box are how a visitor moves at all, feedback is
 * offered to guests on purpose, the tour is mounted but never opens itself at
 * somebody who has not arrived anywhere yet (`?tour=1` opens it, with the
 * steps that read somebody's own data locked), and the chat drawer spends the
 * operator's API keys and writes a file every visitor would share — so a guest
 * gets it `"locked"`: the launcher and a sample answer, with the sign-in where
 * the composer would be (`chat/Locked.tsx`). The
 * investor-profile nudge is an account's, the install nudge is for somebody
 * coming back to their own book, and voice dictation in feedback
 * spends the transcription key a `Writer` route guards.
 */
export const GUEST_CHROME = {
  nav: true,
  search: true,
  feedback: true,
  /** Mounted, so `?tour=1` works — but it never opens itself for a guest. */
  tour: true,
  chat: "locked",
  profilePrompt: false,
  installNudge: false,
  dictation: false,
} as const;
