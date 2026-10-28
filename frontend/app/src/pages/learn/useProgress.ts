/**
 * Which lessons this reader has read, and the press that changes it.
 *
 * A signed-in reader's list lives in their prefs (`POST /learn/progress`); the
 * server's answer replaces the optimistic tick, so two tabs settle on the same
 * list. A guest's lives in this browser only (`logic.ts`): the demo's prefs are
 * shared, and the API refuses a guest's write anyway.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { send } from "../../shell/api";
import { guestDone, setGuestDone, toggled } from "./logic";

export type Progress = {
  /** Null until the curriculum has said, for a signed-in reader. */
  done: ReadonlySet<string> | null;
  mark: (lesson: string, on: boolean) => void;
};

export function useProgress(
  server: readonly string[] | null,
  guest: boolean,
): Progress {
  const [done, setDone] = useState<readonly string[] | null>(() =>
    guest ? guestDone() : server,
  );

  useEffect(() => {
    setDone(guest ? guestDone() : server);
  }, [guest, server]);

  const mark = useCallback(
    (lesson: string, on: boolean) => {
      const before = done ?? [];
      const next = toggled(before, lesson, on);
      setDone(next);
      if (guest) {
        setGuestDone(next);
        return;
      }
      send<{ done: string[] }>(
        "POST",
        "/learn/progress",
        { lesson, done: on },
        { touches: ["/learn"] },
      ).then(
        (out) => setDone(out.done),
        // Put the tick back: a mark that did not save should not look saved.
        () => setDone(before),
      );
    },
    [done, guest],
  );

  const set = useMemo(() => (done ? new Set(done) : null), [done]);
  return { done: set, mark };
}
