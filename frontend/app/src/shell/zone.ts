/**
 * The account's clock: the browser's zone, sent to the server when it moves.
 *
 * The scheduled runs (`notify/schedule.py`) go out at the reader's own wall
 * clock — the 08:30 briefing is 08:30 where they are — so the server needs the
 * zone, and the browser is the one that knows it. Sent once per load and only
 * when it differs: a trip abroad moves the runs with the reader, and a page
 * load at home sends nothing.
 */

import { useEffect } from "react";
import { send } from "./api";
import { useSession } from "./session";

/** The browser's IANA zone, or null where `Intl` will not say. */
export function browserZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** The zone to send, or null when the stored one is already it. */
export function zoneToSend(browser: string | null, stored: string | null | undefined) {
  return browser && browser !== stored ? browser : null;
}

export function useZoneSync(): void {
  const session = useSession();
  const stored = session.prefs.timezone;
  useEffect(() => {
    if (session.guest) return;
    const zone = zoneToSend(browserZone(), stored);
    // A refusal (a zone the server's tz database lacks) leaves the default:
    // nothing on screen depends on it, so there is nothing to say.
    if (zone) send("PATCH", "/prefs", { timezone: zone }).catch(() => undefined);
  }, [session.guest, stored]);
}
