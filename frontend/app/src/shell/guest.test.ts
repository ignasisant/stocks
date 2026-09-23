/**
 * The guest decisions that are worth testing without a DOM.
 *
 * There is no jsdom in this project, on purpose — a shell test that needs a
 * browser is usually a test of React rather than of this app. So the two
 * decisions that would actually hurt if they were wrong are pure functions,
 * and this is them: which screen a session query means, and where a sign-in
 * comes back to.
 */

import { describe, expect, it } from "vitest";
import { screenFor, sessionFrom, type Me, type Prefs } from "./session";
import { signInHref } from "./guest";

const PREFS = { currency: "EUR", language: null } as unknown as Prefs;

describe("screenFor", () => {
  it("gives every query state a screen of its own", () => {
    expect(screenFor("loading")).toBe("pending");
    expect(screenFor("loaded")).toBe("app");
    expect(screenFor("signed-out")).toBe("wall");
    expect(screenFor("failed")).toBe("offline");
  });

  it("does not send a reader whose network dropped to a login page", () => {
    // The branch this file exists for. `failed` and `signed-out` used to
    // render the same fallback, which was harmless while signed-out was the
    // ordinary state — and became advice that cannot work the moment the
    // ordinary state was "guest".
    expect(screenFor("failed")).not.toBe(screenFor("signed-out"));
  });
});

describe("sessionFrom", () => {
  it("gives a guest no address at all", () => {
    const session = sessionFrom({ kind: "guest", email: null }, PREFS, () => {});
    expect(session.guest).toBe(true);
    expect(session.me).toBeNull();
  });

  it("keeps the address of somebody signed in", () => {
    const me: Me = { kind: "session", email: "a@example.com" };
    const session = sessionFrom(me, PREFS, () => {});
    expect(session.guest).toBe(false);
    expect(session.me?.email).toBe("a@example.com");
  });

  it("carries the prefs on both arms, which is what keeps money rendering", () => {
    // `useCurrency()` has ten call sites and none of them were touched when
    // guests landed. That is a property of this shape, not a coincidence.
    for (const kind of ["guest", "session"] as const) {
      expect(sessionFrom({ kind }, PREFS, () => {}).prefs.currency).toBe("EUR");
    }
  });

  it("has no sign-in to offer when the deployment has no provider", () => {
    // A button that sends somebody to a route which 404s is worse than no
    // button, which is the whole reason `/me` answers this question.
    expect(sessionFrom({ kind: "guest" }, PREFS, () => {}).signIn).toBeNull();
    expect(
      sessionFrom({ kind: "guest", sign_in: "/auth/login" }, PREFS, () => {}).signIn,
    ).toBe("/auth/login");
  });
});

describe("signInHref", () => {
  const at = (pathname: string, search = "") =>
    ({ pathname, search }) as unknown as Location;

  it("offers nothing when there is nowhere to sign in", () => {
    expect(signInHref(null, at("/next/"))).toBeNull();
  });

  it("comes back to the screen the reader was on", () => {
    expect(signInHref("/auth/login", at("/next/portfolio", "?tab=fees"))).toBe(
      "/auth/login?next=" + encodeURIComponent("/next/portfolio?tab=fees"),
    );
  });

  it("translates the dev server's base back to where the shell really lives", () => {
    // Under `npm run dev` the document is served by Vite under its asset base.
    // That path on the API's origin — where the round trip always finishes,
    // because it is the redirect URI Google has registered — is a static-file
    // route that 404s.
    expect(signInHref("/auth/login", at("/next-assets/portfolio"))).toBe(
      "/auth/login?next=" + encodeURIComponent("/next/portfolio"),
    );
    expect(signInHref("/auth/login", at("/next-assets/"))).toBe(
      "/auth/login?next=" + encodeURIComponent("/next"),
    );
  });
});
