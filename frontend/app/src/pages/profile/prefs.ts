/**
 * Saving one setting at a time, and believing what comes back.
 *
 * `PATCH /prefs` applies exactly the fields it is sent, so every control here
 * sends its own key and nothing else — which is what makes two people (or two
 * tabs) editing different settings safe, and what keeps `null` meaning "auto"
 * rather than "not mentioned". The response is the whole stored object, and it
 * is what the page renders next: a save that the server changed or refused
 * must not leave the form looking like it took.
 */

import { useCallback, useState } from "react";
import { NotSignedIn, send } from "../../shell/api";
import { useSession, type Prefs } from "../../shell/session";
import { describe } from "./errors";

/** The writable subset, exactly as `api/routes/prefs.PrefsPatch` declares it. */
type Writable = {
  currency: string;
  /** null is "auto" — follow the browser. Not the same as omitting it. */
  language: string | null;
  /** null is "auto" — resolve from the browser's region. */
  tax_residence: string | null;
  tax_filing_status: string;
  tax_other_income: number;
  tax_niit: boolean;
  /** A fraction, never a percentage: 0.09, and the API refuses anything above 1. */
  tax_church_rate: number;
  /** A fraction too. The control asks for percent and divides on the way out. */
  tax_subnational_rate: number;
  notify_digest: boolean;
  notify_weekly: boolean;
  notify_alerts: boolean;
  chat_panel_open: boolean;
  setup_card_dismissed: boolean;
};

/**
 * Changing these two re-renders the whole app: the language decides which
 * catalog is fetched, the currency decides what every figure on screen means.
 */
const WHOLE_APP: ReadonlySet<string> = new Set(["currency", "language"]);

export type Settings = {
  prefs: Prefs;
  /** The field currently in flight, or null. */
  saving: keyof Writable | null;
  /** The field whose last save was refused, and what the API said about it. */
  failure: { field: keyof Writable; message: string } | null;
  save: <K extends keyof Writable>(field: K, value: Writable[K]) => void;
};

export function useSettings(offline: string): Settings {
  const session = useSession();
  // Seeded from the session and replaced by each response. Never patched
  // locally: the server's copy is the one the rest of the app reads.
  const [prefs, setPrefs] = useState<Prefs>(session.prefs);
  const [saving, setSaving] = useState<keyof Writable | null>(null);
  const [failure, setFailure] = useState<Settings["failure"]>(null);

  const save = useCallback(
    <K extends keyof Writable>(field: K, value: Writable[K]) => {
      setSaving(field);
      setFailure(null);
      send<Prefs>("PATCH", "/prefs", { [field]: value }).then(
        (fresh) => {
          setSaving(null);
          setPrefs(fresh);
          // The shell holds its own copy, and the whole app reads it.
          if (WHOLE_APP.has(field)) session.reload();
        },
        (error: unknown) => {
          setSaving(null);
          // A session that ended mid-edit is not this page's error to word:
          // reloading it puts the shell's own sign-in wall up.
          if (error instanceof NotSignedIn) {
            session.reload();
            return;
          }
          setFailure({ field, message: describe(error, offline) });
        },
      );
    },
    [session, offline],
  );

  return { prefs, saving, failure, save };
}
