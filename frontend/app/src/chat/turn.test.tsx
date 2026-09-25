/**
 * The two ways out of a turn that did not work, and the one out of a turn that
 * is still being written.
 *
 * A refusal carries Retry *and* Discard — the Streamlit composer's
 * "error_drop" beside its Retry — because a question the reader has given up
 * on should not sit at the bottom of the thread forever. A failed attachment
 * carries only Discard: it has no question of its own to ask again. And while
 * an answer streams, Send is Stop.
 *
 * Rendered to static markup: the question is what is drawn from a given turn.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";
import { Turn } from "./Turn";
import type { ChatState, Turn as Stored } from "./types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

const refused = (over: Partial<Stored> = {}): Stored => ({
  role: "assistant",
  content: "",
  skills: [],
  web: [],
  action: null,
  error: "chat.api_error",
  ...over,
});

const drawTurn = (turn: Stored, onDrop?: () => void) =>
  renderToStaticMarkup(
    <Turn
      turn={turn}
      skills={[]}
      providers={[]}
      cap={null}
      onRetry={() => {}}
      onDrop={onDrop}
    />,
  );

describe("a refused turn", () => {
  it("offers Retry and Discard", () => {
    const out = drawTurn(refused(), () => {});
    expect(out).toContain("chat.retry");
    expect(out).toContain("chat.error_drop");
  });

  it("offers no Discard where the panel passed none (an older refusal)", () => {
    expect(drawTurn(refused())).not.toContain("chat.error_drop");
  });

  it("does not offer to re-ask the question above a failed attachment", () => {
    const out = drawTurn(refused({ action: "import" }), () => {});
    expect(out).not.toContain("chat.retry");
    expect(out).toContain("chat.error_drop");
  });
});

const state: ChatState = {
  providers: [],
  answering: null,
  preferred: null,
  free_left: null,
  free_cap: null,
  cap_reason: null,
  skills: [],
  skills_mode: "auto",
  skills_selected: [],
  max_manual: 3,
  web: false,
  web_available: false,
  upload_types: ["csv"],
  upload_max_mb: 10,
  voice: false,
};

const drawComposer = (busy: boolean) =>
  renderToStaticMarkup(
    <Composer
      state={state}
      busy={busy}
      reading={false}
      onSend={() => {}}
      onStop={() => {}}
      onSave={() => {}}
      onAttach={() => {}}
      onSettings={() => {}}
    />,
  );

describe("the composer's button", () => {
  it("sends when nothing is being written", () => {
    const out = drawComposer(false);
    expect(out).toContain('aria-label="chat.send"');
    expect(out).not.toContain("chat.stop");
  });

  it("is Stop while an answer streams, and not the form's submit", () => {
    const out = drawComposer(true);
    expect(out).toContain('aria-label="chat.stop"');
    expect(out).not.toContain('aria-label="chat.send"');
    expect(out).not.toContain('type="submit"');
  });
});
