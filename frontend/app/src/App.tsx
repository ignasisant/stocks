import { Suspense, useEffect, useRef } from "react";
import { ApiError } from "./shell/api";
import { Broken, Crash } from "./shell/Crash";
import { browserLang, pinnedLang, Translations, useT } from "./shell/i18n";
import { Layout, MAIN_ID, Skeleton } from "./shell/Layout";
import { pageFor } from "./shell/pages";
import { takeRestore, useRoute } from "./shell/router";
import { SignIn } from "./shell/guest";
import { WithSession } from "./shell/session";

/**
 * The screen for a session that could not be fetched.
 *
 * Its own screen, because `failed` and `signed-out` used to share a fallback
 * and that stopped being harmless: a reader whose network dropped was told to
 * sign in, which is advice that cannot work and hides the real problem. This is
 * the only state in the app where there is nothing to render around — `/me`
 * and `/prefs` are what the chrome itself is built from.
 */
function Offline({ retry, error }: { retry: () => void; error?: unknown }) {
  const t = useT();
  // The one failure worth naming: the account's cloud copy could not be read,
  // so the API refused to serve an empty book whose next save would overwrite
  // it. The server says so with the catalog key for that outage; anything
  // else is the generic "data unavailable".
  const storage =
    error instanceof ApiError && error.detail === "common.storage_restore_failed";
  return (
    <div className="ag-wall">
      <h1>TopStocks</h1>
      <p>{t(storage ? "common.storage_restore_failed" : "common.data_unavailable")}</p>
      <button className="ag-btn" onClick={retry}>
        {t("common.retry")}
      </button>
    </div>
  );
}

/**
 * The wall, for a `signed-out` session query.
 *
 * Nearly unreachable now and kept anyway: `/me` answers "guest" rather than 401,
 * so a 401 here means something the shell cannot serve — a deployment with the
 * guest surface shut off, say. Offering the sign-in is the only useful thing to
 * do about it, and rendering nothing would be a white page.
 */
function SignInWall() {
  const t = useT();
  return (
    <div className="ag-wall">
      <h1>TopStocks</h1>
      <p>{t("common.sign_in")}</p>
      <SignIn label="common.cta_sign_in" />
    </div>
  );
}

function Current() {
  const t = useT();
  const { page, params } = useRoute();
  const entry = pageFor(page);
  const Page = entry.component;

  // The document title is the shell's, not a page's: it is the one piece of
  // chrome a single-page app has to maintain by hand, and a link shared out of
  // here otherwise arrives as a bare "TopStocks" whichever screen it points at.
  // Localized, because the title bar is read in the reader's own language.
  useEffect(() => {
    document.title = `${t(entry.label)} · TopStocks`;
  }, [t, entry.label]);

  // A move to another screen is announced to a screen reader by where focus
  // lands, and a keyboard reader would otherwise keep tabbing from a rail link
  // that no longer matches the page. Focus goes to the page column (not past
  // the first move: loading the app is not a navigation), and a back or
  // forward step returns to where the reader was scrolled — retried while the
  // lazy page fills in, because it is rarely tall enough on the first frame.
  const first = useRef(true);
  const focusKey = `${page}?${params.get("ticker") ?? ""}`;
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    document.getElementById(MAIN_ID)?.focus({ preventScroll: true });
  }, [focusKey]);
  const scrollKey = `${page}?${params.toString()}`;
  useEffect(() => {
    const y = takeRestore();
    if (y === null) return;
    let tries = 0;
    let frame = 0;
    const settle = () => {
      window.scrollTo(0, y);
      if (Math.abs(window.scrollY - y) > 2 && tries++ < 40)
        frame = requestAnimationFrame(settle);
    };
    settle();
    return () => cancelAnimationFrame(frame);
  }, [scrollKey]);

  // A page that throws while rendering keeps the chrome around it: the rail
  // and the search box still take the reader somewhere that works.
  return (
    <Crash
      resetKey={`${page}?${params.toString()}`}
      fallback={<Broken text={t("common.crash")} action={t("common.reload")} />}
    >
      <Suspense fallback={<Skeleton rows={6} />}>
        <Page />
      </Suspense>
    </Crash>
  );
}

export default function App() {
  const browser = browserLang(
    navigator.languages?.length ? navigator.languages : [navigator.language],
  );
  // A landing CTA's `?lang=` wins over the browser for anyone without a stored
  // preference — which is every guest, and the wall and offline screens.
  const fallbackLang = pinnedLang(window.location.search) ?? browser;
  return (
    // The language is the account's preference, and the catalog cannot be
    // fetched until we know it — so the session resolves first and the
    // translations wrap only what is inside it. A guest has no preference, so
    // `/prefs` answers null and the browser's own language wins.
    //
    // `<Layout>` is inside all of this rather than inside the account branch:
    // a guest gets the chrome. Without the rail and the search box an anonymous
    // visitor has no way to reach a second screen, which would make a demo of
    // one page out of a product of eight.
    <WithSession
      pending={<Skeleton rows={6} />}
      wall={
        <Translations lang={fallbackLang}>
          <SignInWall />
        </Translations>
      }
      offline={(retry, error) => (
        <Translations lang={fallbackLang}>
          <Offline retry={retry} error={error} />
        </Translations>
      )}
    >
      {(session) => (
        <Translations
          lang={
            // A signed-in account's stored language is its own; the pinned
            // landing language is only for somebody who has none to store.
            session.guest ? fallbackLang : (session.prefs.language ?? browser)
          }
        >
          <Layout>
            <Current />
          </Layout>
        </Translations>
      )}
    </WithSession>
  );
}
