/**
 * "Refresh this sector" — the Streamlit page's live rescan, over
 * `POST`/`GET /sectors/{sector}/rescan`.
 *
 * A rescan is one sector's whole cohort fetched from Yahoo again: about a
 * minute, which is far longer than a request should be held open. So the POST
 * only starts it and this polls the GET until it lands, then asks the page to
 * reload the cohort — which the server now answers from the fresh scan.
 *
 * Two places offer it, as on the Streamlit page: beside the picker, quieter
 * than it (a rare action that costs a minute of Yahoo), and as the only way out
 * of the empty card for a sector the nightly job never reached. Both read the
 * same hook, so a scan started from one shows its progress in the other.
 *
 * A guest gets neither. The route is a write — it spends the account's hourly
 * budget and the deployment's standing with Yahoo — and a button that answers
 * 403 is worse than no button.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useGuest } from "../../shell/session";

/** How often to ask whether it landed. A scan takes tens of seconds. */
const POLL_MS = 3000;

type Status = {
  sector: string;
  /** idle | running | done | failed */
  state: string;
  started_at: string | null;
  finished_at: string | null;
  as_of: string | null;
  cohort: number;
  /** rate_limited | offline | no_data | error */
  reason: string | null;
};

export type Rescan = {
  /** False for a guest: there is nothing to offer them. */
  available: boolean;
  running: boolean;
  start: () => void;
  /** The line under the control, or null when there is nothing to say. */
  note: string | null;
};

/**
 * One sector's rescan, from the button press to the reload.
 *
 * On arriving at a sector it asks once whether a scan is already running —
 * someone else may have pressed the button a moment ago — and joins it rather
 * than offering to start a second. `idle` on a poll means the process that ran
 * the job is not the one answering (a restart, another instance); the cohort
 * is reloaded anyway, since that is the only way to learn whether it landed.
 */
export function useRescan(sector: string, label: string, onDone: () => void): Rescan {
  const t = useT();
  const guest = useGuest();
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const done = useRef(onDone);
  done.current = onDone;

  const at = `/sectors/${encodeURIComponent(sector)}/rescan`;

  const settle = useCallback(
    (status: Status) => {
      setRunning(false);
      if (status.state === "failed") {
        setNote(t("sector.source_down", { sector: label }));
        return;
      }
      setNote(null);
      done.current();
    },
    [t, label],
  );

  const poll = useCallback(
    (alive: () => boolean) => {
      timer.current = setTimeout(async () => {
        try {
          const status = await get<Status>(at);
          if (!alive()) return;
          if (status.state === "running") poll(alive);
          else settle(status);
        } catch {
          // A failed poll is not a failed scan: keep asking. The job lives on
          // the server either way, and the next answer will say how it ended.
          if (alive()) poll(alive);
        }
      }, POLL_MS);
    },
    [at, settle],
  );

  // One flag per sector visit: leaving the sector (or the page) stops the
  // polling for it, and a late answer cannot flip the next sector's state.
  const live = useRef({ alive: true });

  useEffect(() => {
    const visit = { alive: true };
    live.current = visit;
    setRunning(false);
    setNote(null);
    if (!guest) {
      get<Status>(at)
        .then((status) => {
          if (!visit.alive || status.state !== "running") return;
          setRunning(true);
          setNote(t("sector.refreshing", { sector: label }));
          poll(() => visit.alive);
        })
        .catch(() => {});
    }
    return () => {
      visit.alive = false;
      if (timer.current) clearTimeout(timer.current);
    };
    // `label` and `t` change with the language, which is not a new visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at, guest]);

  const start = useCallback(() => {
    const visit = live.current;
    setRunning(true);
    setNote(t("sector.refreshing", { sector: label }));
    send<Status>("POST", at).then(
      (status) => {
        if (!visit.alive) return;
        if (status.state === "running") poll(() => visit.alive);
        else settle(status);
      },
      (error: unknown) => {
        if (!visit.alive) return;
        setRunning(false);
        if (error instanceof ApiError && error.status === 429) {
          const minutes = Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60));
          setNote(t("sector.rescan_limited", { minutes }));
        } else {
          setNote(t("sector.source_down", { sector: label }));
        }
      },
    );
  }, [at, label, poll, settle, t]);

  return { available: !guest, running, start, note };
}

/** The button itself. Disabled while a scan runs, so a press cannot queue two. */
export function RescanButton({ rescan }: { rescan: Rescan }) {
  const t = useT();
  if (!rescan.available) return null;
  return (
    <button
      type="button"
      className="ag-btn ag-sec-rescan"
      onClick={rescan.start}
      disabled={rescan.running}
      aria-busy={rescan.running}
    >
      {t("sector.refresh")}
    </button>
  );
}
