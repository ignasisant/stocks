/**
 * What the server's slow download is doing, for the corner banner.
 *
 * The banner counts requests, and one of them — the book's price download —
 * can be most of a minute on its own: the bar sat at 11 of 12 for all of it,
 * which reads exactly like a hang. `GET /progress` says which step that
 * download is on and how many names of it are done (`stocks.progress`), so
 * the bar can keep moving for as long as the server does.
 *
 * Polled once a second, and only while the banner is up. A plain `fetch`
 * rather than `shell/api.get`: the poll is not something the reader waits
 * on, so it must not count in the banner it feeds, be memoised, or be kept
 * for the next visit. Any failure stops it for that wait — the banner falls
 * back to counting requests, as it did before.
 */

import { useEffect, useState } from "react";

export type Job = {
  step: string;
  done: number;
  total: number;
  elapsed_s: number;
  step_elapsed_s: number;
  /** How long this step took last time it finished, when known. */
  expected_s: number | null;
};

const POLL_MS = 1000;

export function useServerProgress(active: boolean): Job | null {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!active) {
      setJob(null);
      return;
    }
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const scope = new AbortController();
    const poll = () => {
      fetch("/api/v1/progress", { credentials: "same-origin", signal: scope.signal })
        .then((response) => (response.ok ? response.json() : Promise.reject(response)))
        .then((body: { job: Job | null }) => {
          if (!live) return;
          setJob(body.job);
          timer = setTimeout(poll, POLL_MS);
        })
        .catch(() => live && setJob(null));
    };
    poll();
    return () => {
      live = false;
      clearTimeout(timer);
      scope.abort();
    };
  }, [active]);
  return job;
}

/**
 * How full the bar is, 0–1, and whether that is a measure or a guess.
 *
 * The server's count when it has one (names done of names asked); else the
 * step's time against its last run, held under 95 % so an estimate never
 * claims to be finished; else the page's own requests. `null` share means
 * nothing to measure — the bar is a sweep, not a length.
 */
export function barShare(
  job: Job | null,
  done: number,
  total: number,
): { share: number | null; measured: boolean } {
  if (job && job.total > 0)
    return { share: Math.min(1, job.done / job.total), measured: true };
  if (job && job.expected_s)
    return {
      share: Math.min(0.95, job.step_elapsed_s / job.expected_s),
      measured: false,
    };
  if (total > 1) return { share: Math.min(1, done / total), measured: true };
  return { share: null, measured: false };
}
