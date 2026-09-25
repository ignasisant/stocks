/**
 * Who is asking, and what they have set.
 *
 * Both come from the API — `/me` names the caller, `/prefs` carries the
 * settings — and both are needed before the first page renders: the language
 * decides which catalog to fetch and the reporting currency decides what every
 * figure on screen means. So this is the one place the app waits on the
 * network before showing anything.
 *
 * There are two shapes of caller and the type says so. A **guest** is an
 * anonymous visitor reading the shared demo book — the state the landing's call
 * to action has always dropped people into, and the reason this app can live at
 * `/` at all. An **account** is somebody signed in. What separates them is not
 * a flag a screen may ignore: a guest has no address, so anything that would
 * name one has to be unreachable rather than defensive, which is what
 * `useAccount()` is for.
 */

import { createContext, useContext, type ReactNode } from "react";
import { get } from "./api";
import { useApi, type Query } from "./useApi";

/** What `/me` answers. `sign_in` is null on a deployment with no provider. */
export type Me = {
  kind: "session" | "token" | "guest";
  email?: string | null;
  sign_in?: string | null;
};

/** A caller with an address. Never a guest — that is the whole point. */
export type Account = { kind: "session" | "token"; email: string | null };

export type Prefs = {
  currency: string;
  language: string | null;
  tax_residence: string | null;
  tax_filing_status: string;
  tax_other_income: number;
  tax_niit: boolean;
  tax_church_rate: number;
  tax_subnational_rate: number;
  notify_digest: boolean;
  notify_weekly: boolean;
  notify_alerts: boolean;
  telegram_linked: boolean;
  chat_panel_open: boolean;
  /** What is switched on, put away. */
  setup_card_dismissed: boolean;
  /** What to do first, put away — a different card and a different decision. */
  onboarding_dismissed: boolean;
};

/**
 * Settings and a refetch on both arms, `me` on only one.
 *
 * That asymmetry is deliberate and is the reason this is a union rather than an
 * optional field. Every `useCurrency()` call site reads `prefs`, which both arms
 * have, so a guest Portfolio renders its money without a single edit. The five
 * places that read an address do not compile any more, which is correct: two of
 * them already wrote `me.email ?? ""` into a confirmation box, and under an
 * optional field a guest would have been shown an empty-address "type your
 * email to confirm" rather than a sign-in.
 */
export type Session = { prefs: Prefs; reload: () => void; signIn: string | null } & (
  { guest: true; me: null } | { guest: false; me: Account }
);

const Current = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(Current);
  if (!session) throw new Error("useSession outside <WithSession>");
  return session;
}

/** The reporting currency — what every money figure on screen is quoted in. */
export function useCurrency(): string {
  return useSession().prefs.currency;
}

/** True for an anonymous visitor reading the shared demo book. */
export function useGuest(): boolean {
  return useSession().guest;
}

/**
 * The signed-in account, or a crash.
 *
 * A crash rather than a null, because every caller wants an address and there
 * is no sensible thing to render without one. Mount these behind
 * `<SignedInOnly>` and this never fires; leave one unguarded and it fires on
 * the first guest instead of quietly confirming a destructive act against "".
 */
export function useAccount(): Account {
  const session = useSession();
  if (session.guest) {
    throw new Error("useAccount under a guest — mount this behind <SignedInOnly>");
  }
  return session.me;
}

/** Where to send somebody who wants an account, or null when no IdP is set up. */
export function useSignIn(): string | null {
  return useSession().signIn;
}

export type Screen = "pending" | "app" | "wall" | "offline";

/**
 * Which of four screens a session query means — as a pure function.
 *
 * Extracted from the component because this is the part worth testing and
 * there is no DOM in this project's test run. It also fixes a branch that was
 * merely harmless before: `failed` and `signed-out` used to render the same
 * fallback, so a reader whose network dropped was told to sign in. Now that
 * signed-out is a state almost nobody reaches — `/me` answers "guest" rather
 * than 401 — collapsing the two would mean an outage reads as a login wall.
 */
export function screenFor(state: Query<unknown>["state"]): Screen {
  switch (state) {
    case "loading":
      return "pending";
    case "loaded":
      return "app";
    case "signed-out":
      return "wall";
    case "failed":
      return "offline";
  }
}

/** Build the session a provider hands down. Pure, so a test can call it. */
export function sessionFrom(me: Me, prefs: Prefs, reload: () => void): Session {
  const signIn = me.sign_in ?? null;
  if (me.kind === "guest") return { guest: true, me: null, prefs, reload, signIn };
  return {
    guest: false,
    me: { kind: me.kind, email: me.email ?? null },
    prefs,
    reload,
    signIn,
  };
}

/**
 * Resolve the session, then render the app under it.
 *
 * Named for what it does rather than for who it lets in: it used to be
 * `SignedIn`, which became a lie the moment it started rendering for guests.
 */
export function WithSession({
  children,
  wall,
  offline,
  pending,
}: {
  children: (session: Session) => ReactNode;
  /** Shown for a `signed-out` query — an unexpected state, not the guest one. */
  wall: ReactNode;
  /** Shown when the session itself could not be fetched — and why. */
  offline: (retry: () => void, error: unknown) => ReactNode;
  pending: ReactNode;
}) {
  const query = useApi(
    async () => ({ me: await get<Me>("/me"), prefs: await get<Prefs>("/prefs") }),
    [],
  );
  const screen = screenFor(query.state);
  if (screen === "pending") return <>{pending}</>;
  if (screen === "wall") return <>{wall}</>;
  if (query.state === "failed") return <>{offline(query.retry, query.error)}</>;
  if (query.state !== "loaded") return <>{pending}</>; // unreachable; narrows T
  const session = sessionFrom(query.data.me, query.data.prefs, query.reload);
  return <Current.Provider value={session}>{children(session)}</Current.Provider>;
}
