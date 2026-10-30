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

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { get, send } from "./api";

/** A stamp changes what `/onboarding` answers, and nothing a page shows. */
const SEEN = { touches: ["/onboarding"] };
import { openAssistant } from "./assistant";
import { Icon } from "./Icon";
import { useT } from "./i18n";
import { onIdle } from "./idle";
import { SignIn } from "./guest";
import { canonical } from "./pages";
import { useRoute } from "./router";
import { useGuest } from "./session";
import { Welcome } from "./Welcome";
import {
  after,
  clamp,
  firstLoadInterrupted,
  readPark,
  writePark,
  type Action,
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
 * it: the Claude tab counts how readers reach it (`stocks logs connector`).
 */
function arrive(
  step: { params: Record<string, string>; session?: Record<string, string> },
  mode: "tour" | "news",
): Record<string, string> {
  const query = landing(step);
  if (query.tab === "claude") query.from = mode;
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
 * The first-load decision, once per document: a parked strip, the tour, the
 * news, or nothing — and whether that took the one interruption a first load
 * gets. Pure, and exported for the test.
 */
export function firstLoad(
  state: Pick<State, "steps" | "news" | "tour_done">,
  guide: Guide,
  guest: boolean,
  parked: { mode: "tour" | "news"; at: number } | null,
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
    const length = parked.mode === "tour" ? state.steps.length : state.news.length;
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
  // not the long tour, and Home's start card carries on from there. Opening
  // it retires the tour, stamping the current release, so "what's new" opens
  // for what ships *after* this account arrived rather than never (it waits
  // on `tour_done`) or for the whole backlog. The tour stays one press away
  // by URL and from Profile.
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

export function Tour() {
  const t = useT();
  const guest = useGuest();
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
            const index = next.steps.findIndex((s) => s.id === asked);
            booted.current = true;
            firstLoadInterrupted(true);
            setPlace({ mode: "tour", at: index < 0 ? 0 : index, open: true });
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

  // The strip's position is the tab's, so a reload finds it.
  useEffect(() => {
    writePark(place && !place.open ? { mode: place.mode, at: place.at } : null);
  }, [place]);

  const act = useCallback(
    (action: Action, current: Place) => {
      const { place: next, stamp } = after(current, action);
      // A guest has no account to stamp: `/onboarding/seen` is a write, and a
      // write into the shared guest prefs would be one visitor deciding what
      // the next one has read.
      if (stamp && !guest) {
        void send("POST", "/onboarding/seen", stamp, SEEN).catch(() => undefined);
      }
      setPlace(next);
      if (asked) setParams({ tour: undefined });
    },
    [guest, asked, setParams],
  );

  if (state && welcome) return <Welcome steps={state.steps} onClose={closeWelcome} />;
  if (!state || !place) return null;
  const list = place.mode === "tour" ? state.steps : state.news;
  if (!list.length) return null;
  const at = clamp(place.at, list.length);
  const move = (to: number, open = true) => setPlace({ ...place, at: to, open });

  if (!place.open) {
    return (
      <Strip
        place={{ ...place, at }}
        state={state}
        onResume={() => move(at)}
        onNext={() => move(at + 1)}
        onExit={() => act(place.mode === "tour" ? "finish" : "news_done", place)}
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
  const lead = (s: Step | undefined): React.ReactNode => {
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
          if (s.path !== null) go(canonical(s.path ?? ""), arrive(s, place.mode));
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

  const last = at === state.steps.length - 1;
  return (
    <Modal
      title={t("tour.launch")}
      at={at}
      pages={state.steps.map((s) => ({
        icon: s.icon,
        heading: t(s.title_key),
        body: t(s.body_key),
        // A capability the account has switched on, or has not. Null means
        // the step is a place rather than a switch, and says nothing at all —
        // and a guest has switched nothing on, so the tick would be about the
        // demo.
        badge:
          s.done === null || guest
            ? null
            : s.done
              ? t("tour.active")
              : t("tour.pending"),
        badgeOn: s.done === true,
        note: s.gated && guest ? t("tour.locked") : null,
        lead: leadLabel(s),
      }))}
      lead={lead(state.steps[at])}
      progress={t("tour.progress", { n: at + 1, total: state.steps.length })}
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
  state,
  onResume,
  onNext,
  onExit,
}: {
  place: Place;
  state: State;
  onResume: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  const t = useT();
  const tour = place.mode === "tour";
  const total = tour ? state.steps.length : state.news.length;
  const item = tour ? state.steps[place.at]! : state.news[place.at]!;
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
  lead: React.ReactNode;
  progress: string;
  /** A visible way out of the whole list, in the header. */
  /** Without `onSkip` (the last page) its room is kept, so nothing moves. */
  skip?: { label: string; onSkip: (() => void) | null } | null;
  actions: React.ReactNode;
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
