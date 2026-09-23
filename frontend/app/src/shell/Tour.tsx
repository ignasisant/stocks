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
 * Every way out stamps the account as caught up. That is the whole contract of
 * a modal that interrupts: it gets one chance, and a card shown twice is worse
 * than a card not shown at all.
 */

import { useCallback, useEffect, useState } from "react";

import { get, send } from "./api";
import { openAssistant } from "./assistant";
import { Icon } from "./Icon";
import { useT } from "./i18n";
import { canonical } from "./pages";
import { useRoute } from "./router";

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

type Mode = "closed" | "news" | "tour";

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

export function Tour() {
  const t = useT();
  const { params, go, setParams } = useRoute();
  const [state, setState] = useState<State | null>(null);
  const [mode, setMode] = useState<Mode>("closed");
  const [at, setAt] = useState(0);

  const asked = params.get("tour");

  useEffect(() => {
    let alive = true;
    // Which onboarding this deploy serves. With the conversational guide on
    // (`GUIDE_SURFACE` = "chat", the default) the walkthrough lives in the
    // drawer, and this modal only opens when asked for by URL — and for
    // "what's new", once the guide is behind the account. Unreadable (a
    // guest) reads as the modal, which is what a guest has always had.
    const surface = get<{ surface: string; finished: boolean }>("/guide").catch(() => ({
      surface: "modal",
      finished: true,
    }));
    Promise.all([get<State>("/onboarding"), surface])
      .then(([next, guide]) => {
        if (!alive) return;
        setState(next);
        if (!asked && guide.surface === "chat" && !guide.finished) return;
        // Asked for by URL (`?tour=1`, `?tour=import`) — the deep link the
        // Streamlit tour answers, so a link shared into the app still lands on
        // the step it names.
        if (asked) {
          const index = next.steps.findIndex((s) => s.id === asked);
          setAt(index < 0 ? 0 : index);
          setMode("tour");
          return;
        }
        // The order the Streamlit modal uses: the walkthrough for an account
        // that never finished it, "what's new" for one that did.
        if (!next.tour_done) {
          setAt(0);
          setMode("tour");
          return;
        }
        if (next.news.length) setMode("news");
      })
      .catch(() => {
        // Nothing to draw and nothing to say: the tour is the one thing on
        // screen whose absence a reader cannot notice.
      });
    return () => {
      alive = false;
    };
  }, [asked]);

  const stamp = useCallback(
    (done?: boolean) =>
      void send("POST", "/onboarding/seen", done === undefined ? {} : { done }).catch(
        () => undefined,
      ),
    [],
  );

  const close = useCallback(
    (done?: boolean) => {
      stamp(done);
      setMode("closed");
      setAt(0);
      if (asked) setParams({ tour: undefined });
    },
    [stamp, asked, setParams],
  );

  if (!state || mode === "closed") return null;

  if (mode === "news") {
    const card = state.news[at];
    if (!card) return null;
    const step = state.steps.find((s) => s.id === card.step);
    const last = at === state.news.length - 1;
    return (
      <Modal
        title={t("tour.news_title")}
        intro={t("tour.news_intro")}
        icon={card.icon}
        heading={t(card.title_key)}
        body={t(card.body_key)}
        progress={t("tour.news_progress", { n: at + 1, total: state.news.length })}
        onClose={() => close()}
        actions={
          <>
            {step?.path !== undefined && step?.path !== null ? (
              <button
                type="button"
                className="ag-tour-cta"
                onClick={() => {
                  close();
                  go(canonical(step.path ?? ""), landing(step));
                }}
              >
                {step.cta_key ? t(step.cta_key) : t("tour.goto")}
              </button>
            ) : null}
            {last ? (
              <button type="button" className="ag-tour-btn" onClick={() => close()}>
                {t("tour.news_dismiss")}
              </button>
            ) : (
              <>
                <button type="button" className="ag-tour-quiet" onClick={() => close()}>
                  {t("tour.news_skip")}
                </button>
                <button
                  type="button"
                  className="ag-tour-btn"
                  onClick={() => setAt(at + 1)}
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

  const step = state.steps[at];
  if (!step) return null;
  const last = at === state.steps.length - 1;
  return (
    <Modal
      title={t("tour.launch")}
      icon={step.icon}
      heading={t(step.title_key)}
      body={t(step.body_key)}
      progress={t("tour.progress", { n: at + 1, total: state.steps.length })}
      // A capability the account has switched on, or has not. Null means the
      // step is a place rather than a switch, and says nothing at all.
      badge={
        step.done === null ? null : step.done ? t("tour.active") : t("tour.pending")
      }
      badgeOn={step.done === true}
      onClose={() => close(true)}
      actions={
        <>
          {step.path !== null ? (
            <button
              type="button"
              className="ag-tour-cta"
              onClick={() => {
                close(last);
                go(canonical(step.path ?? ""), landing(step));
              }}
            >
              {step.cta_key ? t(step.cta_key) : t("tour.goto")}
            </button>
          ) : step.session?.chat_panel_open ? (
            /* The assistant is not a page: its step lands nowhere and opens
               the drawer instead. Without this the one stop on the tour that
               explains the assistant was the one stop with no way in. */
            <button
              type="button"
              className="ag-tour-cta"
              onClick={() => {
                close(last);
                openAssistant();
              }}
            >
              {step.cta_key ? t(step.cta_key) : t("tour.goto")}
            </button>
          ) : null}
          {at > 0 ? (
            <button
              type="button"
              className="ag-tour-quiet"
              onClick={() => setAt(at - 1)}
            >
              {t("tour.back")}
            </button>
          ) : null}
          <button
            type="button"
            className="ag-tour-btn"
            onClick={() => (last ? close(true) : setAt(at + 1))}
          >
            {last ? t("tour.finish") : t("tour.next")}
          </button>
        </>
      }
    />
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
        <footer className="ag-tour-foot">{actions}</footer>
      </div>
    </div>
  );
}
