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

import { Attachment } from "./Attachment";
import { Composer } from "./Composer";
import { Turn } from "./Turn";
import type { ChatState, Preview, Turn as Stored } from "./types";

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

const preview: Preview = {
  filename: "U1_20260914.csv",
  label: "Interactive Brokers",
  platform: "ibkr",
  kind: "trades",
  unavailable: false,
  broker: "ibkr",
  needs_broker: false,
  brokers: [{ key: "ibkr", label: "IBKR" }],
  fresh: [
    {
      date: "2026-09-14",
      ticker: "ASML.AS",
      action: "buy",
      quantity: 1,
      price: 633.9,
      currency: "EUR",
      fee: 0,
      note: "",
      why: "",
    },
  ],
  duplicates: [],
  flagged: [],
  rejected: [],
  skipped: [],
  note: "",
  message: { role: "assistant", content: "", action: "import" },
  conversation: null,
};

const drawCard = (busy: boolean, importing?: boolean) =>
  renderToStaticMarkup(
    <Attachment
      preview={preview}
      busy={busy}
      importing={importing}
      onImport={() => {}}
      onDiscard={() => {}}
    />,
  );

describe("the import card", () => {
  it("says it is importing while its rows are written, not only greys out", () => {
    const out = drawCard(true, true);
    expect(out).toContain('role="status"');
    expect(out).toContain("chat.work_importing");
  });

  it("draws no status while it waits on the reader", () => {
    expect(drawCard(false)).not.toContain('role="status"');
  });

  it("draws no status of its own while another file is being read", () => {
    // The panel says "reading" at the bottom; this card is not the one moving.
    expect(drawCard(true, false)).not.toContain("chat.work_importing");
  });
});

/**
 * What an answer's tool calls draw: a page link is a button naming the page
 * (and its tab), and a proposal is a card whose buttons answer it — until it
 * has been answered, when all that is left is where it ended up.
 */
describe("an answer's tool calls", () => {
  const answer = (
    calls: Stored["tool_calls"],
    onDecide?: () => Promise<null>,
    activities: Stored["activities"] = [],
  ) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "⭐ Add AAPL to favorites?",
          skills: [],
          web: [],
          action: null,
          tool_calls: calls,
          activities,
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        onDecide={onDecide}
      />,
    );
  const offer = (state?: string) => ({
    id: "act_1",
    name: "confirm_action",
    args: { kind: "favorite", ticker: "AAPL", args: {} },
    ...(state ? { state } : {}),
  });

  it("draws a page link as a button naming the page and its tab", () => {
    const out = answer([
      { id: "nav", name: "navigate", args: { page: "portfolio", tab: "tax" } },
    ]);
    expect(out).toContain("chat.open_tab");
    expect(out).toContain("<button");
  });

  it("names a tab it has no label for as the page alone", () => {
    const out = answer([
      { id: "nav", name: "navigate", args: { page: "sector", tab: "nope" } },
    ]);
    expect(out).toContain("chat.open_page");
    expect(out).not.toContain("chat.open_tab");
  });

  const form = {
    id: "form_act_1",
    type: "a2ui",
    content: {
      messages: [
        { version: "v0.9", createSurface: { surfaceId: "form_act_1", catalogId: "x" } },
        {
          version: "v0.9",
          updateComponents: {
            surfaceId: "form_act_1",
            components: [
              { id: "root", component: "Row", children: ["f_ticker"] },
              {
                id: "f_ticker",
                component: "TextField",
                label: "Ticker",
                value: { path: "/form/ticker" },
              },
            ],
          },
        },
        {
          version: "v0.9",
          updateDataModel: {
            surfaceId: "form_act_1",
            value: { form: { ticker: "AAPL" } },
          },
        },
      ],
    },
  };

  it("offers Confirm, Edit and Cancel on a proposal that waits", () => {
    const out = answer([offer("pending")], async () => null, [form]);
    expect(out).toContain("chat.action_approve");
    expect(out).toContain("chat.action_edit");
    expect(out).toContain("chat.action_cancel");
  });

  it("offers no Edit when the server sent no form to edit in", () => {
    const out = answer([offer("pending")], async () => null);
    expect(out).toContain("chat.action_approve");
    expect(out).not.toContain("chat.action_edit");
  });

  it("offers nothing to press where nobody can answer it", () => {
    expect(answer([offer("pending")])).not.toContain("chat.action_approve");
  });

  it("shows where an answered proposal ended up, and no buttons", () => {
    const done = answer([offer("done")], async () => null);
    expect(done).toContain("chat.action_done");
    expect(done).not.toContain("chat.action_approve");
    expect(answer([offer("cancelled")], async () => null)).toContain(
      "chat.action_declined",
    );
  });

  it("ignores a tool it does not run", () => {
    expect(answer([{ id: "x", name: "delete_everything", args: {} }])).not.toContain(
      "<button",
    );
  });
});

describe("an answer still being researched", () => {
  const pending = (live: Stored["live"]) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "",
          skills: [],
          web: [],
          action: null,
          pending: true,
          live,
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
      />,
    );

  it("names each lookup as it runs, and what it brought back once it has", () => {
    const out = pending([
      { id: "a", tool: "search_web", arg: "nvidia guidance", out: "5 results" },
      { id: "b", tool: "read_page", arg: "https://a.example" },
    ]);
    expect(out).toContain("search_web");
    expect(out).toContain("→ 5 results");
    expect(out).toContain('aria-busy="true"');
    // The wait still names itself beside the lines.
    expect(out).toContain("chat.work_thinking");
  });
});

describe("an answer that weighed a debate", () => {
  const drawn = (over: Partial<Stored>) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Verdict.",
          skills: [],
          web: [],
          action: null,
          ...over,
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
      />,
    );

  it("shows the bull case before the bear case, above the verdict", () => {
    const out = drawn({
      debate: [
        { side: "bear", text: "- too dear" },
        { side: "bull", text: "- cash flow" },
      ],
    });
    expect(out.indexOf("chat.debate_bull")).toBeLessThan(
      out.indexOf("chat.debate_bear"),
    );
    expect(out.indexOf("chat.debate_bear")).toBeLessThan(out.indexOf("Verdict."));
  });

  it("says a side is still arguing, and that a side failed, while it is written", () => {
    const out = drawn({
      content: "",
      pending: true,
      arguing: [
        { id: "a", side: "bull", text: "", state: "arguing" },
        { id: "b", side: "bear", text: "", state: "failed" },
      ],
    });
    expect(out).toContain("chat.debate_arguing");
    expect(out).toContain("chat.debate_failed");
  });

  it("draws no debate on an answer that had none", () => {
    expect(drawn({})).not.toContain("chat.debate_");
  });
});
