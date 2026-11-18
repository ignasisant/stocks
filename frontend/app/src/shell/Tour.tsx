/**
 * The guided tour and "what's new", over the shell rather than inside a page.
 *
 * Both are one registry (`/onboarding`) and one modal in two modes — a step
 * explains a feature and offers to take you to it; a card announces one thing
 * that shipped and hands you to the step that explains it. Keeping them
 * together is not tidiness: a card whose step this deploy does not carry is
 * dropped server-side, and a client that fetched the two separately could draw
 * an announcement pointing nowhere.
 *
 * The walkthrough a newcomer takes is the section guide: the registry's `core`
 * stops, one per menu entry (`walk`). It is not a dialog. Each stop takes the
 * reader to the section itself and says its two lines from a card in the
 * corner (`Coach`), with the menu entry lit, so what is being described is on
 * screen and still works. The whole list, every stop, stays a dialog for deep
 * links (`?tour=<id>`, `?tour=all`).
 *
 * The tour wins when both are owed (`firstLoad`): an account that has never
 * taken the walkthrough is not the audience for "here is what changed" — it
 * has no before. What's new is for the account that already finished, and the
 * missed release stays owed until then.
 *
 * Every way *out* stamps the account as caught up. That is the whole contract
 * of a modal that interrupts: it gets one chance, and a card shown twice is
 * worse than a card not shown at all. Leaving to look at something is not a way
 * out, though: closing the tour, or following a step or a card to its page,
 * parks it in a strip above the page, on every page, until the reader resumes
 * or ends it — the rules are in `tourPark.ts`, where they can be tested.
 */

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";

import { get, send } from "./api";

/** A stamp changes what `/onboarding` answers, and nothing a page shows. */
const SEEN = { touches: ["/onboarding"] };
/** The guide answered also withdraws Home's offer, which rides `/prefs`. */
const WALKED = { touches: ["/onboarding", "/prefs"] };
import { closeAssistant, drawerWidth, openAssistant, roomBeside } from "./assistant";
import { Icon } from "./Icon";
import { useT } from "./i18n";
import { onIdle } from "./idle";
import { SignIn } from "./guest";
import { canonical } from "./pages";
import { pagePath, routeFor, useRoute } from "./router";
import { useSession } from "./session";
import { phoneNow } from "./useMobile";
import { Welcome } from "./Welcome";
import {
  after,
  ASSISTANT,
  clamp,
  firstLoadInterrupted,
  readPark,
  setGuideStop,
  setTouring,
  writePark,
  type Action,
  type Mode,
  type Place,
} from "./tourPark";
import { useDialog } from "./useDialog";
import { useExitGhost } from "./useSheet";

type Step = {
  id: string;
  icon: string;
  path: string | null;
  params: Record<string, string>;
  /** Registry-shaped state the step wants on arrival (`profile_tab`, …). */
  session: Record<string, string>;
  gated: boolean;
  done: boolean | null;
  /** One of the few stops the tour walks when it is simply started. */
  core?: boolean;
  title_key: string;
  body_key: string;
  cta_key: string | null;
};

type Card = {
  version: string;
  date: string;
  slug: string;
  icon: string;
  step: string | null;
  title_key: string;
  body_key: string;
};

type State = {
  version: string;
  seen_version: string | null;
  tour_done: boolean;
  steps: Step[];
  news: Card[];
  setup: Record<string, boolean>;
  explore: Record<string, boolean>;
};

/**
 * The query a step lands with.
 *
 * `params` is already query-shaped. `session` is not: the registry describes
 * client state to seed on arrival, and this shell puts that intent in the
 * URL — the Profile's tab is `?tab=`. Without this mapping every Profile step
 * lands on the default tab, so "turn on notifications" opened Preferences and the
 * reader was told to look for a control that was not there.
 */
export function landing(step: {
  params: Record<string, string>;
  session?: Record<string, string>;
}): Record<string, string> {
  const query = { ...step.params };
  const tab = step.session?.profile_tab;
  if (tab && !query.tab) query.tab = tab;
  return query;
}

/**
 * `landing`, plus where the reader came from for the one page that reports
 * it: the MCP tab counts how readers reach it (`stocks logs connector`).
 */
function arrive(
  step: { params: Record<string, string>; session?: Record<string, string> },
  mode: "tour" | "news",
): Record<string, string> {
  const query = landing(step);
  if (query.tab === "mcp") query.from = mode;
  return query;
}

/** `**bold**`, the one piece of markup the catalogs use in this copy. */
function Rich({ text }: { text: string }) {
  return (
    <>
      {text
        .split("**")
        .map((part, i) =>
          i % 2 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>,
        )}
    </>
  );
}

type Guide = { surface: string; finished: boolean };

/**
 * The stops a walkthrough pages through: the section guide's for "tour",
 * every one for "all". A registry with no core stop marked walks everything,
 * so the guide can never be an empty one.
 */
export function walk<S extends { core?: boolean }>(steps: S[], mode: Mode): S[] {
  if (mode === "all") return steps;
  const core = steps.filter((s) => s.core);
  return core.length ? core : steps;
}

/**
 * Where `?tour=` opens: `1` is the section guide from the top, `all` the whole
 * list, and a step's id that step — in the guide when it is one of its
 * stops, in the whole list otherwise, so a deep link to any stop still lands
 * on it. An id nobody knows opens the guide.
 */
export function asking(steps: { id: string; core?: boolean }[], asked: string): Place {
  if (asked === "all") return { mode: "all", at: 0, open: true };
  const short = walk(steps, "tour").findIndex((s) => s.id === asked);
  if (short >= 0) return { mode: "tour", at: short, open: true };
  const full = steps.findIndex((s) => s.id === asked);
  if (full >= 0) return { mode: "all", at: full, open: true };
  return { mode: "tour", at: 0, open: true };
}

/**
 * The first-load decision, once per document: a parked strip, the tour, the
 * news, or nothing — and whether that took the one interruption a first load
 * gets. Pure, and exported for the test.
 */
export function firstLoad(
  state: Pick<State, "steps" | "news" | "tour_done">,
  guide: Guide,
  guest: boolean,
  parked: { mode: Mode; at: number } | null,
): {
  place: Place | null;
  interrupted: boolean;
  forget?: boolean;
  /** Open the short first-login welcome instead of the tour. */
  welcome?: boolean;
} {
  // A tour parked in this tab outlives a reload, as the strip, exactly where
  // it was left — rather than re-opening at step one over the page the reader
  // went to look at. A strip is not an interruption.
  let forget = false;
  if (parked) {
    const length =
      parked.mode === "news"
        ? state.news.length
        : walk(state.steps, parked.mode).length;
    if (length) {
      return {
        place: { mode: parked.mode, at: clamp(parked.at, length), open: false },
        interrupted: false,
      };
    }
    forget = true;
  }
  // Never automatic for a guest: the tour is a per-account place in a
  // sequence, and the shared guest prefs would hand the next visitor this
  // one's progress through it.
  if (guest) return { place: null, interrupted: false, forget };
  // The conversational guide is walking this account through in the drawer:
  // that is the first load's interruption, and the modal stays shut.
  if (guide.surface === "chat" && !guide.finished) {
    return { place: null, interrupted: true, forget };
  }
  // The card surface: a newcomer gets three rows in a pop-up (`Welcome`),
  // which offers the import and the section guide and opens neither. Opening
  // it retires the automatic tour, so a reload does not bring the pop-up
  // back; whether the account is still new, and so spared "what's new", is
  // the server's to say (`onboarding.newcomer`), not this flag's.
  if (guide.surface === "card" && !state.tour_done) {
    return { place: null, interrupted: true, forget, welcome: true };
  }
  // The walkthrough for an account that never finished it, "what's new" for
  // one that did.
  if (!state.tour_done && state.steps.length) {
    return { place: { mode: "tour", at: 0, open: true }, interrupted: true, forget };
  }
  if (state.news.length) {
    return { place: { mode: "news", at: 0, open: true }, interrupted: true, forget };
  }
  return { place: null, interrupted: false, forget };
}

/** Where the address bar is, read now rather than from a render ago. */
function standing(): { page: string; params: URLSearchParams } {
  return routeFor(pagePath(window.location.pathname), window.location.search);
}

/**
 * The section a guide stop points the menu at: its page's slug, or the
 * assistant, which is a panel.
 */
function section(step: Step): string {
  return step.path === null ? ASSISTANT : canonical(step.path);
}

export function Tour() {
  const t = useT();
  const { guest, reload } = useSession();
  const { params, go, setParams } = useRoute();
  const [state, setState] = useState<State | null>(null);
  // Null: nothing running. `open: false`: parked in the strip above the page.
  const [place, setPlace] = useState<Place | null>(null);
  const [welcome, setWelcome] = useState(false);
  const closeWelcome = useCallback(() => setWelcome(false), []);

  const asked = params.get("tour");
  // The automatic decisions — restore a parked strip, open for a newcomer,
  // announce a release — are taken once per document. Re-taking them when
  // `?tour=` leaves the URL would race the stamp that just retired the tour,
  // and re-open it at step one because the refetch beat the write.
  const booted = useRef(false);

  useEffect(() => {
    let alive = true;
    // A guest's tour is only ever asked for (`?tour=`) or already parked in
    // this tab; anything else would be a request per page view for a modal
    // that is never going to open itself.
    if (guest && !asked && !booted.current && !readPark()) {
      booted.current = true;
      firstLoadInterrupted(false);
      return;
    }
    // Which onboarding this deploy serves. "card" (the default) opens
    // nothing for a newcomer; "chat" walks them through in the drawer; with
    // either, this modal opens only when asked for by URL — and for "what's
    // new", once the onboarding is behind the account. Unreadable (a guest)
    // reads as the modal, which is what a guest has always had.
    const load = () => {
      const surface: Promise<Guide> = guest
        ? Promise.resolve({ surface: "modal", finished: true })
        : get<Guide>("/guide").catch(() => ({
            surface: "modal",
            finished: true,
          }));
      Promise.all([get<State>("/onboarding"), surface])
        .then(([next, guide]) => {
          if (!alive) return;
          setState(next);
          // Asked for by URL (`?tour=1`, `?tour=import`), so a link shared into
          // the app lands on the step it names. A guest may ask too: the steps
          // that read somebody's own data are shown locked, not hidden.
          if (asked) {
            booted.current = true;
            firstLoadInterrupted(true);
            setPlace(asking(next.steps, asked));
            return;
          }
          if (booted.current) return;
          booted.current = true;
          const decided = firstLoad(next, guide, guest, readPark());
          if (decided.forget) writePark(null);
          if (decided.welcome) {
            // Stamped on open, not on close: a welcome seen twice is no longer
            // one, and a reload before closing it must not bring it back.
            setWelcome(true);
            void send("POST", "/onboarding/seen", { done: true }, SEEN).catch(
              () => undefined,
            );
          }
          firstLoadInterrupted(decided.interrupted);
          setPlace(decided.place);
        })
        .catch(() => {
          // Nothing to draw and nothing to say: the tour is the one thing on
          // screen whose absence a reader cannot notice.
          firstLoadInterrupted(false);
        });
    };
    // Asked for by URL, now; otherwise once the browser is idle. Two
    // requests per page load for a modal that mostly stays shut, and the
    // page's own figures go first — the strip, when there is one, follows
    // within the idle timeout.
    const cancel = asked ? (load(), () => {}) : onIdle(load);
    return () => {
      alive = false;
      cancel();
    };
  }, [asked, guest]);

  // The strip's position is the tab's, so a reload finds it. Not before the
  // first load has read it: nothing is on screen yet at mount, and writing
  // that down would erase the strip the reload came back for.
  useEffect(() => {
    if (!booted.current) return;
    writePark(place && !place.open ? { mode: place.mode, at: place.at } : null);
  }, [place]);

  // A page's first-visit tip waits while any of this is up (`PageTip`).
  useEffect(() => {
    setTouring(place !== null || welcome);
  }, [place, welcome]);
  useEffect(() => () => setTouring(false), []);

  // The section guide goes to the section it is talking about: on opening and
  // on every move, never on a render. The page under the card stays the
  // reader's — a link followed from it must not be pulled back to the stop.
  const guiding = place?.mode === "tour" && place.open ? place.at : null;
  const ready = state !== null;
  // The drawer the assistant stop put up, to be put away again when the guide
  // moves on to a page or ends. One the reader already had open is left be.
  const openedChat = useRef(false);
  const putChatBack = () => {
    if (!openedChat.current) return;
    openedChat.current = false;
    closeAssistant();
  };
  // Parked, the reader stepped out of the guide and may be using the panel by
  // now: it is theirs, and finishing from the strip later leaves it open.
  // Ended or skipped, it goes with the guide.
  const off = guiding === null;
  const parked = place !== null && !place.open;
  useEffect(() => {
    if (!off) return;
    if (parked) openedChat.current = false;
    else putChatBack();
  }, [off, parked]);
  const latest = useRef({ state, guest, asked, go, setParams });
  latest.current = { state, guest, asked, go, setParams };
  useEffect(() => {
    const now = latest.current;
    if (guiding === null || !now.state) {
      setGuideStop(null);
      return;
    }
    const stops = walk(now.state.steps, "tour");
    const stop = stops[clamp(guiding, stops.length)];
    if (!stop) return;
    setGuideStop(section(stop));
    // `?tour=` has been answered. Dropped in place, before the move pushes a
    // new entry: left behind, the back button would land on it and start the
    // guide over.
    if (now.asked) now.setParams({ tour: undefined });
    // A guest's locked stop is a sign-in wall rather than a section; the card
    // says so and offers the account instead.
    if (stop.gated && now.guest) return;
    if (stop.path === null) {
      // The assistant is a panel. Where it fits beside the page it opens with
      // the stop; where it would cover the page (a phone, a narrow window, a
      // drawer dragged wide) it would cover the card too, so the card offers
      // it instead.
      const beside = !phoneNow() && roomBeside(drawerWidth());
      if (stop.session?.chat_panel_open && beside) {
        if (document.documentElement.dataset.chat === undefined)
          openedChat.current = true;
        openAssistant();
      }
      return;
    }
    putChatBack();
    const slug = canonical(stop.path);
    const query = arrive(stop, "tour");
    const here = standing();
    const there =
      here.page === slug &&
      Object.entries(query).every(([key, value]) => here.params.get(key) === value);
    if (!there) now.go(slug, query);
  }, [guiding, ready]);
  useEffect(() => () => setGuideStop(null), []);

  const act = useCallback(
    (action: Action, current: Place) => {
      const { place: next, stamp } = after(current, action);
      // A guest has no account to stamp: `/onboarding/seen` is a write, and a
      // write into the shared guest prefs would be one visitor deciding what
      // the next one has read.
      if (stamp && !guest) {
        void send("POST", "/onboarding/seen", stamp, stamp.walked ? WALKED : SEEN)
          // Home's offer is a setting the session holds a copy of.
          .then(() => (stamp.walked ? reload() : undefined))
          .catch(() => undefined);
      }
      setPlace(next);
      if (asked) setParams({ tour: undefined });
    },
    [guest, asked, setParams, reload],
  );

  if (state && welcome) {
    return (
      <Welcome
        steps={state.steps}
        onClose={closeWelcome}
        onTour={() => {
          setWelcome(false);
          setPlace({ mode: "tour", at: 0, open: true });
        }}
      />
    );
  }
  if (!state || !place) return null;
  const steps = place.mode === "news" ? state.steps : walk(state.steps, place.mode);
  const list = place.mode === "news" ? state.news : steps;
  if (!list.length) return null;
  const at = clamp(place.at, list.length);
  const move = (to: number, open = true) => setPlace({ ...place, at: to, open });

  if (!place.open) {
    return (
      <Strip
        place={{ ...place, at }}
        list={list}
        onResume={() => move(at)}
        onNext={() => move(at + 1)}
        onExit={() => act(place.mode === "news" ? "news_done" : "finish", place)}
      />
    );
  }

  // "Take me there": a way off the dialog to the step's page, or into the
  // drawer for the assistant (not a page), or, for a guest on a step that
  // reads somebody's own data, an account. Null when there is nowhere to go.
  const leadLabel = (s: Step | undefined): string | null => {
    if (!s) return null;
    if (s.gated && guest) return t("common.cta_sign_in");
    if (s.path !== null || (s.session?.chat_panel_open && !guest)) {
      return s.cta_key ? t(s.cta_key) : t("tour.goto");
    }
    return null;
  };
  const lead = (s: Step | undefined): ReactNode => {
    const label = leadLabel(s);
    if (!s || label === null) return null;
    if (s.gated && guest) {
      return (
        <SignIn
          label="common.cta_sign_in"
          className="ag-tour-btn ag-tour-lead"
          wall="tour"
        />
      );
    }
    return (
      <button
        type="button"
        className="ag-tour-btn ag-tour-lead"
        onClick={() => {
          act("goto", place);
          if (s.path !== null)
            go(
              canonical(s.path ?? ""),
              arrive(s, place.mode === "news" ? "news" : "tour"),
            );
          else openAssistant();
        }}
      >
        {label}
      </button>
    );
  };
  const back =
    at > 0 ? (
      <button type="button" className="ag-tour-quiet" onClick={() => move(at - 1)}>
        {t("tour.back")}
      </button>
    ) : null;

  if (place.mode === "news") {
    const stepOf = (card: Card) => state.steps.find((s) => s.id === card.step);
    const last = at === state.news.length - 1;
    return (
      <Modal
        title={t("tour.news_title")}
        intro={t("tour.news_intro")}
        at={at}
        pages={state.news.map((card) => {
          const step = stepOf(card);
          return {
            icon: card.icon,
            heading: t(card.title_key),
            body: t(card.body_key),
            note: step?.gated && guest ? t("tour.locked") : null,
            lead: leadLabel(step),
          };
        })}
        lead={lead(stepOf(state.news[at]!))}
        progress={t("tour.news_progress", { n: at + 1, total: state.news.length })}
        onClose={() => act("dismiss", place)}
        // Like the tour's skip: the way out of the list sits in the header,
        // so the footer is the same two buttons on every card.
        skip={{
          label: t("tour.news_skip"),
          onSkip: last ? null : () => act("news_done", place),
        }}
        actions={
          <>
            {back}
            <button
              type="button"
              className="ag-tour-cta"
              onClick={() => (last ? act("news_done", place) : move(at + 1))}
            >
              {last ? t("tour.news_dismiss") : t("tour.next")}
            </button>
          </>
        }
      />
    );
  }

  const last = at === steps.length - 1;

  if (place.mode === "tour") {
    const s = steps[at]!;
    const locked = s.gated && guest;
    // What the card cannot do for the reader by moving the page: an account
    // for a guest, and the assistant on a phone, where it is the whole screen
    // and would cover the card that opened it.
    const way = locked ? (
      <SignIn label="common.cta_sign_in" className="ag-tour-btn" wall="tour" />
    ) : s.path === null && s.session?.chat_panel_open && !guest ? (
      <button
        type="button"
        className="ag-tour-btn ag-coach-open"
        onClick={openAssistant}
      >
        {s.cta_key ? t(s.cta_key) : t("tour.goto")}
      </button>
    ) : null;
    return (
      <Coach
        at={at}
        total={steps.length}
        icon={s.icon}
        heading={t(s.title_key)}
        body={t(s.body_key)}
        badge={s.done === true && !guest ? t("tour.active") : null}
        note={locked ? t("tour.locked") : null}
        way={way}
        progress={t("tour.progress", { n: at + 1, total: steps.length })}
        onBack={at > 0 ? () => move(at - 1) : null}
        onNext={() => (last ? act("complete", place) : move(at + 1))}
        // Skipping is an answer, like finishing; X and Escape only put the
        // guide away, in the strip above the page.
        onSkip={last ? null : () => act("finish", place)}
        onPark={() => act("dismiss", place)}
      />
    );
  }

  return (
    <Modal
      title={t("tour.launch")}
      at={at}
      pages={steps.map((s) => ({
        icon: s.icon,
        heading: t(s.title_key),
        body: t(s.body_key),
        // A capability the account has switched on. One still off says
        // nothing, as on the guide's card: "not set up yet" over an optional
        // one read as a fault. A guest has switched nothing on, so the tick
        // would be about the demo.
        badge: s.done === true && !guest ? t("tour.active") : null,
        badgeOn: s.done === true,
        note: s.gated && guest ? t("tour.locked") : null,
        lead: leadLabel(s),
      }))}
      lead={lead(steps[at])}
      progress={t("tour.progress", { n: at + 1, total: steps.length })}
      // Parks rather than ends: the tour is what the reader came for, and the
      // strip above the page is how they get back into it.
      onClose={() => act("dismiss", place)}
      // The way out in words, on every step but the last (whose Finish is the
      // same thing). Escape and the scrim only park the tour, and neither is a
      // control anybody can see — on a phone, step one of twenty offered Next
      // and nothing else.
      skip={{ label: t("tour.skip"), onSkip: last ? null : () => act("finish", place) }}
      actions={
        <>
          {back}
          {/* Moving on is the tour's own action, so it is the filled one and
              sits last. */}
          <button
            type="button"
            className="ag-tour-cta"
            onClick={() => (last ? act("finish", place) : move(at + 1))}
          >
            {last ? t("tour.finish") : t("tour.next")}
          </button>
        </>
      }
    />
  );
}

/** Whether something the reader opened over the page owns Escape right now. */
function covered(): boolean {
  return (
    document.documentElement.dataset.chat !== undefined ||
    document.querySelector('[aria-modal="true"], dialog[open], .ag-nav-sheet') !== null
  );
}

/**
 * Whether Escape belongs to what the reader is in the middle of on the page:
 * a field they are typing in (the search box closes its panel on it), or
 * something they popped open (a "?" note, a menu). Those have their own
 * Escape, and it must not put the guide away as well.
 */
function claimed(at: Element | null): boolean {
  if (!at) return false;
  return (
    at.matches(
      'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [aria-expanded="true"]',
    ) || at.closest('[role="menu"], [role="listbox"], [role="dialog"]') !== null
  );
}

/**
 * One stop of the section guide: a card in the corner of the section it is
 * describing.
 *
 * Not a dialog, and no scrim: the reader was just taken to this page and the
 * point is that they can see and use it. So focus is not trapped and the page
 * is not inert; the card takes focus when it opens and is a landmark after
 * that. It sits under anything opened on top of the page (the assistant, a
 * dialog), which is why Escape is only its own when nothing else has a claim.
 *
 * Portalled out of the page column: `.ag-main` is a size container, and a
 * container is the containing block of anything fixed inside it. Into the
 * shell rather than the body, which is where the phone bar's height
 * (`--dock`) is in scope.
 */
function Coach({
  at,
  total,
  icon,
  heading,
  body,
  badge,
  note,
  way,
  progress,
  onBack,
  onNext,
  onSkip,
  onPark,
}: {
  at: number;
  total: number;
  icon: string;
  heading: string;
  body: string;
  /** Already done by this account (the import), said beside the heading. */
  badge: string | null;
  note: string | null;
  /** A way in the card has to offer, because moving the page could not. */
  way: ReactNode;
  progress: string;
  onBack: (() => void) | null;
  onNext: () => void;
  /** Null on the last stop, whose own button is the way out. */
  onSkip: (() => void) | null;
  onPark: () => void;
}) {
  const t = useT();
  const id = useId();
  const { page, params } = useRoute();
  // What `App` takes for a move to another screen, and refocuses on.
  const screen = `${page}?${params.get("ticker") ?? ""}`;
  const card = useRef<HTMLElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const back = useRef<HTMLButtonElement>(null);

  // The page keeps room under its last row for the card (`shell.css`), as
  // much as the card is tall: two lines of copy in one language are three in
  // another.
  useEffect(() => {
    const root = document.documentElement;
    const el = card.current;
    root.dataset.guide = "";
    const measure = () => {
      if (el) root.style.setProperty("--coach", `${el.offsetHeight}px`);
    };
    measure();
    const watch =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    if (el) watch?.observe(el);
    return () => {
      watch?.disconnect();
      delete root.dataset.guide;
      root.style.removeProperty("--coach");
    };
  }, []);

  // Every way out is a button in the card, which leaves with it. Focus goes
  // to the page column, where a navigation would have put it, rather than
  // falling to the top of the document. A layout effect: its cleanup still
  // finds the pressed button in the tree.
  useLayoutEffect(() => {
    const el = card.current;
    return () => {
      if (!el?.contains(document.activeElement)) return;
      document.getElementById("ag-main")?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // Where the key was pressed, not where focus is now: the panel's own
      // Escape may already have closed it and moved focus to the page.
      const at = event.target instanceof Element ? event.target : null;
      if (!card.current?.contains(at) && (covered() || claimed(at))) return;
      onPark();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onPark]);

  // A move changes the page, and a page change sends focus to the page column
  // (`App`): walking the guide from the keyboard would mean finding Next again
  // after every stop. A press made from inside the card hands focus back to
  // the same button once the stop, and then its page, have arrived — unless
  // the reader has put it somewhere of their own since.
  // Opening is such a press too: whatever asked for the guide (the welcome,
  // Home's card, the strip) has just left the screen with focus on it.
  const held = useRef<{ which: "next" | "back"; until: number } | null>({
    which: "next",
    until: Date.now() + 4000,
  });
  const hold = (which: "next" | "back", run: () => void) => () => {
    held.current = card.current?.contains(document.activeElement)
      ? { which, until: Date.now() + 4000 }
      : null;
    run();
  };
  useEffect(() => {
    const kept = held.current;
    if (!kept || Date.now() > kept.until) return;
    const timer = window.setTimeout(() => {
      const active = document.activeElement;
      const free =
        !active ||
        active === document.body ||
        active.id === "ag-main" ||
        card.current?.contains(active);
      if (!free) return;
      const target =
        kept.which === "back" ? (back.current ?? next.current) : next.current;
      target?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [at, screen]);

  const last = onSkip === null;
  return createPortal(
    <aside
      ref={card}
      className="ag-coach"
      aria-labelledby={`${id}-t ${id}-h`}
      style={{ "--coach-done": (at + 1) / total } as CSSProperties}
    >
      <header className="ag-coach-head">
        <span className="ag-coach-step" id={`${id}-t`}>
          {progress}
        </span>
        <button
          type="button"
          className="ag-x ag-coach-x"
          aria-label={t("common.close")}
          onClick={onPark}
        >
          <Icon name="close" size={16} />
        </button>
      </header>
      <span className="ag-coach-bar" aria-hidden="true" />
      {/* As in the dialog: the stop changes under a button that keeps focus,
          so the region says where the reader now is. */}
      <span className="ag-sr" aria-live="polite">
        {`${progress}: ${heading}`}
      </span>
      <div key={at} className="ag-coach-stop ag-redraw">
        <h2 className="ag-coach-h" id={`${id}-h`}>
          <Icon name={icon} />
          {heading}
          {badge ? (
            <span className="ag-tour-badge ag-tour-on ag-coach-badge">
              <Icon name="check" size={12} />
              {badge}
            </span>
          ) : null}
        </h2>
        <p className="ag-coach-body">
          <Rich text={body} />
        </p>
        {note ? <p className="ag-coach-note">{note}</p> : null}
        {way ? <div className="ag-coach-way">{way}</div> : null}
      </div>
      <footer className="ag-coach-foot">
        {onSkip ? (
          <button
            type="button"
            className="ag-tour-quiet ag-coach-skip"
            onClick={onSkip}
          >
            {t("tour.skip")}
          </button>
        ) : null}
        <span className="ag-coach-moves">
          {onBack ? (
            <button
              ref={back}
              type="button"
              className="ag-tour-quiet"
              onClick={hold("back", onBack)}
            >
              {t("tour.back")}
            </button>
          ) : null}
          <button
            ref={next}
            type="button"
            className="ag-tour-cta"
            onClick={hold("next", onNext)}
          >
            {last ? t("tour.finish") : t("tour.next")}
          </button>
        </span>
      </footer>
    </aside>,
    document.querySelector(".ag-shell") ?? document.body,
  );
}

/**
 * The parked tour: one line above the page body, on every page.
 *
 * Deliberately not a modal — the point of "take me there" is that the reader is
 * looking at the real page. The strip says where they are and holds the ways
 * on: back into the modal, straight to the next item, or out for good
 * (`_resume_strip` / `_news_strip`).
 */
function Strip({
  place,
  list,
  onResume,
  onNext,
  onExit,
}: {
  place: Place;
  /** The list the place is in: the walked steps, or the cards. */
  list: (Step | Card)[];
  onResume: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  const t = useT();
  const tour = place.mode !== "news";
  const total = list.length;
  const item = list[place.at]!;
  return (
    <div
      className="ag-tour-strip"
      role="region"
      aria-label={t(tour ? "tour.launch" : "tour.news_title")}
    >
      <Icon name={item.icon} />
      <span className="ag-tour-strip-text">
        <Rich
          text={t(tour ? "tour.strip_progress" : "tour.news_strip_progress", {
            n: place.at + 1,
            total,
            title: t(item.title_key),
          })}
        />
      </span>
      <span className="ag-tour-strip-actions">
        <button type="button" className="ag-tour-btn" onClick={onResume}>
          {t(tour ? "tour.resume" : "tour.news_resume")}
        </button>
        {place.at < total - 1 ? (
          <button type="button" className="ag-tour-quiet" onClick={onNext}>
            {t("tour.next")}
          </button>
        ) : null}
        <button type="button" className="ag-tour-quiet" onClick={onExit}>
          {t(tour ? "tour.exit" : "tour.news_dismiss")}
        </button>
      </span>
    </div>
  );
}

/** One page of the dialog: a step or a card, as words. */
type Page = {
  icon: string;
  heading: string;
  body: string;
  badge?: string | null;
  badgeOn?: boolean;
  /** A line under the body — why the way in is an account. */
  note?: string | null;
  /** The label of "take me there", so a hidden page is as tall as its button. */
  lead?: string | null;
};

function PageBody({ page, id }: { page: Page; id?: string }) {
  return (
    <>
      <h2 className="ag-tour-h" id={id ? `${id}-h` : undefined}>
        {/* The registry names a Material Symbols ligature; this shell draws
            the handful it has as inline SVG and simply omits the rest. An
            icon is decoration on a heading that already says the thing. */}
        <Icon name={page.icon} />
        {page.heading}
      </h2>
      {page.badge ? (
        <span className={page.badgeOn ? "ag-tour-badge ag-tour-on" : "ag-tour-badge"}>
          {page.badge}
        </span>
      ) : null}
      <p className="ag-tour-body" id={id ? `${id}-b` : undefined}>
        <Rich text={page.body} />
      </p>
      {page.note ? <p className="ag-tour-note">{page.note}</p> : null}
    </>
  );
}

function Modal({
  title,
  intro,
  pages,
  at,
  lead,
  progress,
  skip,
  actions,
  onClose,
}: {
  title: string;
  intro?: string;
  /** Every page of the list, so the dialog is as tall as the tallest. */
  pages: Page[];
  at: number;
  /** The current page's "take me there", live. */
  lead: ReactNode;
  progress: string;
  /** A visible way out of the whole list, in the header. */
  /** Without `onSkip` (the last page) its room is kept, so nothing moves. */
  skip?: { label: string; onSkip: (() => void) | null } | null;
  actions: ReactNode;
  onClose: () => void;
}) {
  const id = useId();
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  useDialog(card);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const page = pages[at]!;

  return (
    <div ref={scrim} className="ag-tour-scrim" role="presentation" onClick={onClose}>
      <div
        ref={card}
        tabIndex={-1}
        className="ag-tour ag-tour-paged"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-t ${id}-h`}
        aria-describedby={`${id}-b`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ag-tour-head">
          <span className="ag-tour-title" id={`${id}-t`}>
            {title}
          </span>
          <span className="ag-tour-head-end">
            <span className="ag-tour-progress">
              <Rich text={progress} />
            </span>
            {skip?.onSkip ? (
              <button
                type="button"
                className="ag-tour-quiet ag-tour-skip"
                onClick={skip.onSkip}
              >
                {skip.label}
              </button>
            ) : skip ? (
              /* The last page has no way out but its own button; the header
                 keeps the skip's room so the footer does not move. */
              <span
                className="ag-tour-quiet ag-tour-skip ag-tour-held"
                aria-hidden="true"
              >
                {skip.label}
              </span>
            ) : null}
          </span>
        </header>
        {/* Next keeps focus on its own button, so the new step would change
            under a screen reader in silence: the region speaks where the
            reader now is. Filled from the first render, so only a change is
            announced, never the opening (the dialog's name covers that). */}
        <span className="ag-sr" aria-live="polite">
          {`${progress.replaceAll("**", "")}: ${page.heading}`}
        </span>
        {intro ? <p className="ag-tour-intro">{intro}</p> : null}
        {/* Every page is laid in the same cell and only the current one is
            visible, so the dialog is as tall as its tallest page and Next
            stays under the finger from the first page to the last. The
            current page is keyed on its place, so moving on cross-fades it. */}
        <div className="ag-tour-pages">
          {pages.map((p, i) =>
            i === at ? (
              <div key={`at-${i}`} className="ag-tour-page ag-redraw">
                <PageBody page={p} id={id} />
                {lead ? <div className="ag-tour-go">{lead}</div> : null}
              </div>
            ) : (
              <div key={i} className="ag-tour-page" aria-hidden="true">
                <PageBody page={p} />
                {p.lead ? (
                  <div className="ag-tour-go">
                    <span className="ag-tour-btn">{p.lead}</span>
                  </div>
                ) : null}
              </div>
            ),
          )}
        </div>
        <footer className="ag-tour-foot">{actions}</footer>
      </div>
    </div>
  );
}
