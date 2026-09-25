/**
 * The guided tour and "what's new", over the shell rather than inside a page.
 *
 * Both are one registry (`/onboarding`) and one modal in two modes, exactly as
 * in the Streamlit app — a step explains a feature and offers to take you to
 * it; a card announces one thing that shipped and hands you to the step that
 * explains it. Keeping them together is not tidiness: a card whose step this
 * deploy does not carry is dropped server-side, and a client that fetched the
 * two separately could draw an announcement pointing nowhere.
 *
 * The tour wins when both are owed, which is `onboarding.maybe_open()`'s rule
 * and not this file's to re-decide: an account that has never taken the
 * walkthrough is not the audience for "here is what changed" — it has no
 * before. What's new is for the account that already finished, and the missed
 * release stays owed until then.
 *
 * Every way *out* stamps the account as caught up. That is the whole contract
 * of a modal that interrupts: it gets one chance, and a card shown twice is
 * worse than a card not shown at all. Leaving to look at something is not a way
 * out, though: closing the tour, or following a step or a card to its page,
 * parks it in a strip above the page, on every page, until the reader resumes
 * or ends it — the rules are in `tourPark.ts`, where they can be tested.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { get, send } from "./api";
import { openAssistant } from "./assistant";
import { Icon } from "./Icon";
import { useT } from "./i18n";
import { canonical } from "./pages";
import { useRoute } from "./router";
import { useGuest } from "./session";
import {
  after,
  clamp,
  firstLoadInterrupted,
  readPark,
  writePark,
  type Action,
  type Place,
} from "./tourPark";

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
 * what the Streamlit page seeds in session state, and this shell puts the same
 * intent in the URL — the Profile's tab is `?tab=`. Without this mapping every
 * Profile step lands on the default tab, so "set up Telegram" opened
 * Preferences and the reader was told to look for a control that was not
 * there.
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
): { place: Place | null; interrupted: boolean; forget?: boolean } {
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
  // The order the Streamlit modal uses: the walkthrough for an account that
  // never finished it, "what's new" for one that did.
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

  const asked = params.get("tour");
  // The automatic decisions — restore a parked strip, open for a newcomer,
  // announce a release — are taken once per document, as `maybe_open` takes
  // them once per Streamlit session. Re-taking them when `?tour=` leaves the
  // URL would race the stamp that just retired the tour, and re-open it at
  // step one because the refetch beat the write.
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
    // Which onboarding this deploy serves. With the conversational guide on
    // (`GUIDE_SURFACE` = "chat", the default) the walkthrough lives in the
    // drawer, and this modal only opens when asked for by URL — and for
    // "what's new", once the guide is behind the account. Unreadable (a
    // guest) reads as the modal, which is what a guest has always had.
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
        // Asked for by URL (`?tour=1`, `?tour=import`) — the deep link the
        // Streamlit tour answers, so a link shared into the app still lands on
        // the step it names. A guest may ask too (Streamlit lets them): the
        // steps that read somebody's own data are shown locked, not hidden.
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
        firstLoadInterrupted(decided.interrupted);
        setPlace(decided.place);
      })
      .catch(() => {
        // Nothing to draw and nothing to say: the tour is the one thing on
        // screen whose absence a reader cannot notice.
        firstLoadInterrupted(false);
      });
    return () => {
      alive = false;
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
        void send("POST", "/onboarding/seen", stamp).catch(() => undefined);
      }
      setPlace(next);
      if (asked) setParams({ tour: undefined });
    },
    [guest, asked, setParams],
  );

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

  if (place.mode === "news") {
    const card = state.news[at]!;
    const step = state.steps.find((s) => s.id === card.step);
    const last = at === state.news.length - 1;
    const locked = !!step?.gated && guest;
    return (
      <Modal
        title={t("tour.news_title")}
        intro={t("tour.news_intro")}
        icon={card.icon}
        heading={t(card.title_key)}
        body={t(card.body_key)}
        progress={t("tour.news_progress", { n: at + 1, total: state.news.length })}
        onClose={() => act("dismiss", place)}
        note={locked ? t("tour.locked") : null}
        actions={
          <>
            {step && step.path !== null ? (
              <button
                type="button"
                className="ag-tour-cta"
                disabled={locked}
                onClick={() => {
                  act("goto", place);
                  go(canonical(step.path ?? ""), landing(step));
                }}
              >
                {step.cta_key ? t(step.cta_key) : t("tour.goto")}
              </button>
            ) : null}
            {at > 0 ? (
              <button
                type="button"
                className="ag-tour-quiet"
                onClick={() => move(at - 1)}
              >
                {t("tour.back")}
              </button>
            ) : null}
            {last ? (
              <button
                type="button"
                className="ag-tour-btn"
                onClick={() => act("news_done", place)}
              >
                {t("tour.news_dismiss")}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="ag-tour-quiet"
                  onClick={() => act("news_done", place)}
                >
                  {t("tour.news_skip")}
                </button>
                <button
                  type="button"
                  className="ag-tour-btn"
                  onClick={() => move(at + 1)}
                >
                  {t("tour.next")}
                </button>
              </>
            )}
          </>
        }
      />
    );
  }

  const step = state.steps[at]!;
  const last = at === state.steps.length - 1;
  const locked = step.gated && guest;
  const cta = step.cta_key ? t(step.cta_key) : t("tour.goto");
  return (
    <Modal
      title={t("tour.launch")}
      icon={step.icon}
      heading={t(step.title_key)}
      body={t(step.body_key)}
      progress={t("tour.progress", { n: at + 1, total: state.steps.length })}
      // A capability the account has switched on, or has not. Null means the
      // step is a place rather than a switch, and says nothing at all — and a
      // guest has switched nothing on, so the tick would be about the demo.
      badge={
        step.done === null || guest
          ? null
          : step.done
            ? t("tour.active")
            : t("tour.pending")
      }
      badgeOn={step.done === true}
      note={locked ? t("tour.locked") : null}
      // Parks rather than ends: the tour is what the reader came for, and the
      // strip above the page is how they get back into it.
      onClose={() => act("dismiss", place)}
      actions={
        <>
          {step.path !== null ? (
            <button
              type="button"
              className="ag-tour-cta"
              disabled={locked}
              onClick={() => {
                act("goto", place);
                go(canonical(step.path ?? ""), landing(step));
              }}
            >
              {cta}
            </button>
          ) : step.session?.chat_panel_open && !guest ? (
            /* The assistant is not a page: its step lands nowhere and opens
               the drawer instead. Without this the one stop on the tour that
               explains the assistant was the one stop with no way in. A guest
               has no drawer to open. */
            <button
              type="button"
              className="ag-tour-cta"
              onClick={() => {
                act("goto", place);
                openAssistant();
              }}
            >
              {cta}
            </button>
          ) : null}
          {at > 0 ? (
            <button
              type="button"
              className="ag-tour-quiet"
              onClick={() => move(at - 1)}
            >
              {t("tour.back")}
            </button>
          ) : null}
          <button
            type="button"
            className="ag-tour-btn"
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

function Modal({
  title,
  intro,
  icon,
  heading,
  body,
  progress,
  badge,
  badgeOn,
  note,
  actions,
  onClose,
}: {
  title: string;
  intro?: string;
  icon: string;
  heading: string;
  body: string;
  progress: string;
  badge?: string | null;
  badgeOn?: boolean;
  /** A line under the body — why the button beside it is disabled. */
  note?: string | null;
  actions: React.ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ag-tour-scrim" role="presentation" onClick={onClose}>
      <div
        className="ag-tour"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ag-tour-head">
          <span className="ag-tour-title">{title}</span>
          <span className="ag-tour-progress">
            <Rich text={progress} />
          </span>
        </header>
        {intro ? <p className="ag-tour-intro">{intro}</p> : null}
        <h2 className="ag-tour-h">
          {/* The registry names a Material Symbols ligature; this shell draws
              the handful it has as inline SVG and simply omits the rest. An
              icon is decoration on a heading that already says the thing. */}
          <Icon name={icon} />
          {heading}
        </h2>
        {badge ? (
          <span className={badgeOn ? "ag-tour-badge ag-tour-on" : "ag-tour-badge"}>
            {badge}
          </span>
        ) : null}
        <p className="ag-tour-body">
          <Rich text={body} />
        </p>
        {note ? <p className="ag-tour-note">{note}</p> : null}
        <footer className="ag-tour-foot">{actions}</footer>
      </div>
    </div>
  );
}
