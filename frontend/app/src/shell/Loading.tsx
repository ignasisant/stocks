/**
 * What the shell says while a page is loading — and that it finished.
 *
 * A wait that holds still reads as a hang. Each of these keeps showing that
 * the work is alive (seconds climbing, a bar the server moves, a glyph that
 * pulses), says what is being done in words rather than "loading", and ends
 * with a close the reader can see: the banner says "Done" before it goes, the
 * stale line says "updated", content fades in where the grey bars were.
 *
 * - `ActivityBanner`: the corner banner, for requests out past
 *   `activity.SLOW_MS`. Its bar follows the server's own download when it has
 *   one (`shell/progress`); its hint grows with the wait.
 * - `StaleNotice`: figures older than they look — the server's stale answers,
 *   and the last visit's figures drawn while the live ones are out — with the
 *   re-ask counting down, then the press to ask again once nothing will.
 * - `Skeleton`: a block on its way, captioned with what it waits for after a
 *   few seconds, and whatever replaces it faded in.
 *
 * Under reduced motion every one still changes — text, counts, a slow opacity
 * pulse — it only stops sliding.
 */

import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { useT } from "./i18n";
import { kindOf, useActivity } from "./activity";
import { barShare, useServerProgress } from "./progress";
import { retryStale, useKeptSince, useRetry, useStaleSince } from "./freshness";
import { usePresence } from "./useSheet";
import "../ui/ui.css";

/** Re-render every `every` ms while it is not null; returns the time now. */
function useNow(every: number | null): number {
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (every === null) return;
    const id = window.setInterval(tick, every);
    return () => window.clearInterval(id);
  }, [every]);
  return Date.now();
}

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** How long "Done" stays up once everything has landed. */
const DONE_MS = 900;

/** Seconds into a wait at which its hint changes: still going, can take a
 * while, reload if it never ends. */
const HINTS: [number, string][] = [
  [60, "activity.hint_very_long"],
  [25, "activity.hint_long"],
  [8, "activity.hint_slow"],
];

const STEPS: Record<string, string> = {
  "prices.tail": "activity.step_tail",
  "prices.rebase": "activity.step_rebase",
  "prices.full": "activity.step_full",
};

/** The hint for a wait `seconds` long, or the server's own estimate. */
export function hintFor(seconds: number, expected: number | null): string | null {
  if (expected !== null && expected >= 3) return "activity.expected";
  return HINTS.find(([at]) => seconds >= at)?.[1] ?? null;
}

/**
 * The corner banner: what is taking a while, how long it has, and how far
 * along it is.
 *
 * Silent until a request has been out for `activity.SLOW_MS` — a page that
 * answers promptly never shows it. Bottom-left on a phone would sit on the tab
 * bar, so it is bottom-right everywhere, above the assistant's button. It
 * slides in, and when the last request lands it says so for a moment before
 * it slides back out the way it came; a reader leaving the screen is not a
 * finish, so that one just goes.
 */
export function ActivityBanner() {
  const t = useT();
  const activity = useActivity();
  const busy = activity.slow.length > 0;
  // Nothing slow left. A reader who left the screen (`activity.forget`, which
  // zeroes the count) did not see anything finish; anything else did — even
  // if the content that landed has fired a few quick requests of its own.
  const finished = !busy && activity.total > 0;
  const [done, setDone] = useState(false);
  const shown = useRef(activity);
  if (busy) shown.current = activity;
  const was = useRef(false);
  useEffect(() => {
    if (busy) {
      was.current = true;
      setDone(false);
      return;
    }
    if (!was.current) return;
    was.current = false;
    if (!finished) return;
    setDone(true);
    const id = window.setTimeout(() => setDone(false), DONE_MS);
    return () => window.clearTimeout(id);
  }, [busy, finished]);
  const { mounted, leaving } = usePresence(busy || done);
  const job = useServerProgress(busy);
  const now = useNow(busy ? 1000 : null);
  if (!mounted) return null;

  const { slow, since } = shown.current;
  const seconds = since === null ? 0 : Math.max(0, Math.floor((now - since) / 1000));
  const finishing = !busy;
  const { share, measured } = finishing
    ? { share: 1, measured: true }
    : barShare(job, shown.current.done, shown.current.total);
  const hint = finishing ? null : hintFor(seconds, job?.expected_s ?? null);
  const step = job ? STEPS[job.step] : undefined;
  return (
    <div
      className="ag-activity"
      role="status"
      aria-live="polite"
      data-leaving={leaving || undefined}
      data-done={finishing || undefined}
    >
      <div className="ag-activity-head">
        <span className="ag-activity-title">
          <span className="ag-activity-glyph" aria-hidden="true">
            {finishing ? "✓" : "✻"}
          </span>
          {t(finishing ? "activity.done" : "activity.title")}
        </span>
        {finishing ? null : (
          <span className="ag-activity-count" aria-hidden="true">
            {t("common.seconds", { s: seconds })}
          </span>
        )}
      </div>
      {finishing ? null : (
        <ul className="ag-activity-list">
          {slow.slice(0, 3).map((kind) => (
            <li key={kind}>{t(kind)}</li>
          ))}
        </ul>
      )}
      {step && job && !finishing ? (
        <p className="ag-activity-step">
          {t(step)}
          {job.total > 0
            ? ` · ${t("activity.names", { done: job.done, total: job.total })}`
            : null}
        </p>
      ) : null}
      <div
        className="ag-activity-bar"
        aria-hidden="true"
        data-sweep={share === null || undefined}
        data-guess={(share !== null && !measured) || undefined}
      >
        {share === null ? null : (
          <div style={{ width: `${Math.round(share * 100)}%` }} />
        )}
      </div>
      {hint ? (
        <p className="ag-activity-hint">
          {t(hint, { s: Math.round(job?.expected_s ?? 0) })}
        </p>
      ) : null}
    </div>
  );
}

/** How long "Data updated" stays once the stale line has nothing to say. */
const FRESH_MS = 2500;
/** Last visit's figures say so only past this: most live answers beat it. */
const KEPT_MS = 1000;

function formatWhen(at: number): string {
  return new Date(at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * One line, on every page, whenever a figure on it is older than it looks.
 *
 * The API says so per response (`X-Data-Stale-Since`) when the price source
 * refused and the last good data stood in; this reads the oldest such mark and
 * goes away on its own once a live answer replaces it. Here rather than in each
 * card because the same download feeds half the cards on a screen, and one
 * sentence beats six badges saying the same thing.
 *
 * It also says what is being done about it: the seconds to the next re-ask,
 * that one is out, or — once `useApi` has stopped asking — a press to ask
 * again now. When the figures come back live it says that, briefly, rather
 * than just vanishing. And the last visit's figures (`shell/keep`), drawn
 * while the live ones are out, say whose they are past a second.
 */
export function StaleNotice() {
  const t = useT();
  const since = useStaleSince();
  const retry = useRetry();
  const kept = useKeptSince();
  const now = useNow(since !== null && retry.due !== null ? 1000 : null);

  const [fresh, setFresh] = useState(false);
  const wasStale = useRef(false);
  useEffect(() => {
    if (since !== null) {
      wasStale.current = true;
      setFresh(false);
      return;
    }
    if (!wasStale.current) return;
    wasStale.current = false;
    setFresh(true);
    const id = window.setTimeout(() => setFresh(false), FRESH_MS);
    return () => window.clearTimeout(id);
  }, [since]);

  const [keptShown, setKeptShown] = useState(false);
  useEffect(() => {
    if (kept === null) {
      setKeptShown(false);
      return;
    }
    const id = window.setTimeout(() => setKeptShown(true), KEPT_MS);
    return () => window.clearTimeout(id);
  }, [kept]);

  const stale = since !== null;
  const keptLine = !stale && kept !== null && keptShown;
  const open = stale || keptLine || fresh;
  const { mounted, leaving } = usePresence(open);
  const last = useRef<"stale" | "kept" | "fresh">("fresh");
  if (stale) last.current = "stale";
  else if (keptLine) last.current = "kept";
  else if (fresh) last.current = "fresh";
  if (!mounted) return null;

  const mode = last.current;
  return (
    <p
      className="ag-stale"
      role="status"
      data-mode={mode}
      data-leaving={leaving || undefined}
    >
      {mode === "stale" && since !== null ? (
        <>
          <span>{t("common.stale_notice", { when: formatWhen(since) })}</span>{" "}
          {retry.asking ? (
            <span className="ag-stale-next">
              <span className="ag-work-glyph" aria-hidden="true">
                ✻
              </span>{" "}
              {t("common.stale_asking")}
            </span>
          ) : retry.due !== null ? (
            <span className="ag-stale-next">
              {t("common.stale_next", {
                s: Math.max(1, Math.ceil((retry.due - now) / 1000)),
              })}
            </span>
          ) : (
            <button type="button" className="ag-stale-retry" onClick={retryStale}>
              {t("common.stale_retry")}
            </button>
          )}
        </>
      ) : mode === "kept" && kept !== null ? (
        <>
          <span className="ag-work-glyph" aria-hidden="true">
            ✻
          </span>{" "}
          {t("common.kept_notice", { when: formatWhen(kept) })}
        </>
      ) : (
        <>
          <span className="ag-stale-ok" aria-hidden="true">
            ✓
          </span>{" "}
          {t("common.fresh_again")}
        </>
      )}
    </p>
  );
}

/**
 * What a block on its way is waiting for: the URLs its fetch asked for
 * (`useApi`'s loading state), handed down by `Loaded` to whatever skeleton it
 * draws — so a page's own skeleton gets the caption too, as long as it draws
 * a `Skeleton` somewhere inside.
 */
export const WaitingFor = createContext<string[] | undefined>(undefined);

/** Seconds before a skeleton says what it waits for, and before its count. */
const CAPTION_S = 3;
const COUNT_S = 8;
/** A skeleton seen for less than this is replaced without a fade: a flash of
 * grey and a fade on top of it is two motions for one thing. */
const FADE_AFTER_MS = 400;
const FADE_MS = 200;

/**
 * Fade in what replaces `ref`'s element once it unmounts — the content that
 * landed where the grey bars were.
 *
 * The neighbours are read on every commit; at unmount, a microtask later (once
 * React has put the new content in), whatever now sits between them in the
 * same parent is what arrived. A skeleton still on the page then was
 * StrictMode re-running effects, and nothing fades.
 */
function useArrivalFade(ref: React.RefObject<HTMLElement | null>, since: number): void {
  const spot = useRef<{ parent: Node; prev: Node | null; next: Node | null } | null>(
    null,
  );
  useLayoutEffect(() => {
    const el = ref.current;
    if (el?.parentNode)
      spot.current = {
        parent: el.parentNode,
        prev: el.previousSibling,
        next: el.nextSibling,
      };
  });
  useEffect(() => {
    const el = ref.current;
    return () => {
      const at = spot.current;
      if (!at || !el || Date.now() - since < FADE_AFTER_MS || reducedMotion()) return;
      queueMicrotask(() => {
        if (el.isConnected || !(at.parent as Element).isConnected) return;
        const { parent, prev, next } = at;
        if (
          (prev && prev.parentNode !== parent) ||
          (next && next.parentNode !== parent)
        )
          return;
        let node = prev ? prev.nextSibling : parent.firstChild;
        while (node && node !== next) {
          if (node instanceof HTMLElement && typeof node.animate === "function")
            node.animate([{ opacity: 0 }, { opacity: 1 }], {
              duration: FADE_MS,
              easing: "cubic-bezier(0.2, 0, 0, 1)",
            });
          node = node.nextSibling;
        }
      });
    };
  }, [ref, since]);
}

/**
 * A block of the page that is still loading — the shape of what is coming.
 *
 * A status with the word in it, not a hidden shape: the grey bars are all a
 * sighted reader needs, and without the word a screen reader hears nothing
 * where the block will land. Past a few seconds the bars say what they are
 * waiting for ("Downloading prices…"), and past a few more how long it has
 * been: a block that has said nothing for ten seconds looks broken. `shape`
 * lays the bars out like what they stand in for (`ag-skeleton-*` classes).
 */
export function Skeleton({
  rows = 3,
  shape,
}: {
  rows?: number;
  shape?: "kpis" | "table" | "chart";
}) {
  const t = useT();
  const urls = useContext(WaitingFor);
  const [start] = useState(() => Date.now());
  const ref = useRef<HTMLDivElement>(null);
  const now = useNow(1000);
  useArrivalFade(ref, start);
  const seconds = Math.floor((now - start) / 1000);
  const what = t(urls?.[0] ? kindOf(urls[0]) : "activity.other");
  return (
    <div className="ag-skeleton" role="status" ref={ref} data-shape={shape}>
      <span className="ag-sr">{t("common.loading")}</span>
      {shape === "kpis" ? (
        <div className="ag-skeleton-kpis">
          {Array.from({ length: rows }, (_, i) => (
            <div className="ag-skeleton-kpi" key={i}>
              <div className="ag-skeleton-row" data-w="label" />
              <div className="ag-skeleton-row" data-w="figure" />
            </div>
          ))}
        </div>
      ) : shape === "chart" ? (
        <div className="ag-skeleton-row" data-w="chart" />
      ) : (
        Array.from({ length: rows }, (_, i) => (
          <div
            className="ag-skeleton-row"
            data-cells={shape === "table" || undefined}
            key={i}
          >
            {shape === "table" ? (
              <>
                <span />
                <span />
                <span />
              </>
            ) : null}
          </div>
        ))
      )}
      {seconds >= CAPTION_S ? (
        <span className="ag-skeleton-cap" aria-hidden="true">
          <span className="ag-work-glyph">✻</span>
          {t("common.waiting_for", { what })}
          {seconds >= COUNT_S ? (
            <span className="ag-skeleton-secs">
              {t("common.seconds", { s: seconds })}
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
