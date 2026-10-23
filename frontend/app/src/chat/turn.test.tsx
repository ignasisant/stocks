/**
 * The two ways out of a turn that did not work, and the one out of a turn that
 * is still being written.
 *
 * A refusal carries Retry *and* Discard, because a question the reader has
 * given up on should not sit at the bottom of the thread forever. A failed
 * attachment carries only Discard: it has no question of its own to ask
 * again. And while an answer streams, Send is Stop.
 *
 * Rendered to static markup: the question is what is drawn from a given turn.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const send = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock("../shell/api", async (original) => ({
  ...(await original<typeof import("../shell/api")>()),
  send,
}));

import { Attachment } from "./Attachment";
import { Composer } from "./Composer";
import { rateAt, Turn, undoMemory } from "./Turn";
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

const drawTurn = (turn: Stored, onDrop?: () => void, askRating = true) =>
  renderToStaticMarkup(
    <Turn
      turn={turn}
      skills={[]}
      providers={[]}
      cap={null}
      onRetry={() => {}}
      onDrop={onDrop}
      askRating={askRating}
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

describe("switching AI on a refusal", () => {
  const draw = (turn: Stored, onDrop?: () => void) =>
    renderToStaticMarkup(
      <Turn
        turn={turn}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        onDrop={onDrop}
        switchTo={[
          { id: "free", label: "TopStocks AI" },
          { id: "claude", label: "Claude" },
          { id: "openai", label: "ChatGPT" },
        ]}
        onSwitch={() => {}}
        onPickAi={() => {}}
      />,
    );

  it("offers two other providers and the settings screen", () => {
    const out = draw(refused(), () => {});
    expect(out.match(/chat\.try_with/g)).toHaveLength(2);
    expect(out).toContain("chat.pick_ai");
  });

  it("is only on the newest refusal", () => {
    expect(draw(refused())).not.toContain("chat.try_with");
  });

  it("is not offered under a failed attachment", () => {
    expect(draw(refused({ action: "import" }), () => {})).not.toContain("chat.pick_ai");
  });
});

describe("the reader's own question", () => {
  it("is drawn folded, with no Show more until something was clipped", () => {
    const out = drawTurn(
      refused({ role: "user", error: undefined, content: "Revisa esta lectura" }),
    );
    expect(out).toContain("ag-chat-fold");
    expect(out).toContain("Revisa esta lectura");
    expect(out).not.toContain("chat.show_more");
  });
});

const state: ChatState = {
  providers: [],
  answering: null,
  preferred: null,
  free_left: null,
  free_cap: null,
  deep_units: 2,
  cap_reason: null,
  skills: [],
  skills_mode: "auto",
  skills_selected: [],
  max_manual: 3,
  upload_types: ["csv"],
  upload_max_mb: 10,
  voice: false,
};

const drawComposer = (busy: boolean, over: Partial<ChatState> = {}) =>
  renderToStaticMarkup(
    <Composer
      state={{ ...state, ...over }}
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

describe("the composer's research switch", () => {
  it("starts at normal, its cost unsaid until it is turned on", () => {
    const out = drawComposer(false);
    expect(out).toContain("chat.depth_mode");
    expect(out).toMatch(/aria-pressed="true"[^>]*>chat.depth_normal/);
    expect(out).not.toContain("chat.depth_cost");
    expect(out).toContain('placeholder="chat.placeholder"');
  });

  describe("in depth, once picked", () => {
    const own = {
      id: "claude",
      label: "Claude",
      models: [],
      model: "",
      needs_key: true,
      has_key: true,
      console_url: "",
      key_placeholder: "",
      key_days_left: null,
      domain: null,
    };
    const kept = (value: string | null) =>
      vi.stubGlobal("window", {
        location: { pathname: "/", search: "" },
        matchMedia: () => ({ matches: false }),
        addEventListener: () => {},
        removeEventListener: () => {},
        localStorage: { getItem: () => value },
      });

    it("stays on for an account its own key answers", () => {
      kept("1");
      const out = drawComposer(false, { providers: [own], answering: "claude" });
      expect(out).toMatch(/aria-pressed="true"[^>]*>chat.depth_deep/);
      expect(out).toContain("chat.depth_hint_kept");
      expect(out).toContain('placeholder="chat.placeholder_deep"');
    });

    it("is for one question on the free chain, whatever was kept", () => {
      kept("1");
      const out = drawComposer(false);
      expect(out).toMatch(/aria-pressed="true"[^>]*>chat.depth_normal/);
    });
  });

  it("is the segmented control every other one-of-a-few choice is", () => {
    const out = drawComposer(false);
    expect(out).toMatch(
      /class="ag-seg"[^>]*role="group"[^>]*aria-label="chat.depth_mode"/,
    );
    expect(out).toMatch(/aria-label="chat.skills_mode"/);
  });
});

describe("the composer's paperclip", () => {
  it("offers a CSV by the type it was saved as, not only by its extension", () => {
    // Chrome on Android turns `.csv` into `text/comma-separated-values` for the
    // picker, which then greys out a download saved as `text/csv`.
    expect(drawComposer(false)).toMatch(/accept="\.csv,[^"]*text\/csv/);
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

  it("offers the full-width review, shut until it is asked for", () => {
    const out = drawCard(false);
    expect(out).toContain("chat.import_review");
    expect(out).not.toContain('role="dialog"');
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

  const ledger = (state: string, change: number | null) => ({
    id: "act_2",
    name: "confirm_action",
    args: {
      kind: "mark_transfer",
      ticker: "GRF.MC",
      args: {},
      book: { summary: "Book the GRF.MC sale as a transfer", change },
    },
    state,
  });
  const undoable = (state: string, change: number | null, undo = true) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Done.",
          skills: [],
          web: [],
          action: null,
          tool_calls: [ledger(state, change)],
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        onDecide={async () => null}
        onUndo={undo ? async () => null : undefined}
      />,
    );

  it("offers Undo on a ledger edit that went through, and only there", () => {
    expect(undoable("done", 7)).toContain("chat.action_undo");
    expect(undoable("done", 7, false)).not.toContain("chat.action_undo");
    expect(undoable("done", null)).not.toContain("chat.action_undo");
    expect(answer([offer("done")], async () => null)).not.toContain("chat.action_undo");
  });

  it("says a ledger edit taken back is undone, with nothing to press", () => {
    const out = undoable("undone", 7);
    expect(out).toContain("chat.action_undone");
    // The foot's copy button is the only one an answer may carry here.
    expect(out).not.toMatch(/<button(?![^>]*chat\.copy)/);
  });

  it("offers no Edit on a ledger edit even beside a surface", () => {
    const out = renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Book it?",
          skills: [],
          web: [],
          action: null,
          tool_calls: [ledger("pending", null)],
          activities: [{ ...form, id: "form_act_2" }],
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        onDecide={async () => null}
      />,
    );
    expect(out).toContain("chat.action_approve");
    expect(out).not.toContain("chat.action_edit");
  });

  it("ignores a tool it does not run", () => {
    expect(answer([{ id: "x", name: "delete_everything", args: {} }])).not.toMatch(
      /<button(?![^>]*chat\.copy)/,
    );
  });
});

describe("an answer still being researched", () => {
  const pending = (live: Stored["live"], plan?: Stored["plan"]) =>
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
          plan,
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

  it("reads a lookup the model explained as its reason, in the reader's words", () => {
    const out = pending([
      { id: "a", tool: "search_web", arg: "asml news", why: "Noticias de ASML de hoy" },
    ]);
    expect(out).toContain("Noticias de ASML de hoy");
    expect(out).not.toContain("search_web");
  });

  it("shows a deep research's plan above its lookups, ticked as it goes", () => {
    const out = pending(
      [{ id: "a", tool: "get_quotes", arg: "NVDA" }],
      [
        { text: "Precio de NVDA", done: true },
        { text: "Noticias de AMD", done: false },
      ],
    );
    expect(out).toContain("Noticias de AMD");
    expect(out.indexOf("ag-chat-plan")).toBeLessThan(out.indexOf("ag-chat-live"));
    // Done in words for a screen reader, not only as a check mark.
    expect(out.match(/chat\.plan_done/g)).toHaveLength(1);
    expect(out).toMatch(/<ol class="ag-chat-plan" aria-label="chat\.plan"/);
  });

  it("draws no plan once the answer is in", () => {
    const out = renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Done.",
          skills: [],
          web: [],
          action: null,
          plan: [{ text: "Precio de NVDA", done: true }],
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
      />,
    );
    expect(out).not.toContain("ag-chat-plan");
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

describe("memory on a turn", () => {
  const drawn = (over: Partial<Stored>, onMemory?: () => void) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Answer.",
          skills: [],
          web: [],
          action: null,
          ...over,
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        onOpenThread={() => {}}
        onMemory={onMemory}
      />,
    );
  const saved = {
    op: "added" as const,
    id: "m1",
    text: "I hold for 5 years",
    kind: "goal",
  };
  const corrected = {
    ...saved,
    op: "updated" as const,
    text: "I hold for 10 years",
    before: "I hold for 5 years",
    auto: true,
  };
  const earlier = {
    thread: "c_old",
    title: "Nvidia",
    when: "2026-09-01T10:00:00Z",
    snippet: "We said NVDA was dear",
  };

  it("says what was saved, with its undo and the way to the memory screen", () => {
    const out = drawn({ learned: [saved] }, () => {});
    expect(out).toContain("chat.mem_updated");
    expect(out).toContain("I hold for 5 years");
    expect(out).toContain("chat.mem_undo");
    expect(out).toContain("chat.mem_manage");
  });

  it("does not quote a memory the command's own answer already quotes", () => {
    const out = drawn({ action: "memory", learned: [saved] });
    expect(out).toContain("chat.mem_updated");
    expect(out).not.toContain("ag-chat-memo-text");
  });

  it("says a forgotten memory was forgotten", () => {
    const out = drawn({ learned: [{ ...saved, op: "deleted" }] });
    expect(out).toContain("chat.mem_forgotten");
    expect(out).not.toContain("chat.mem_updated");
  });

  it("says a memory learned unasked was learned, and names it", () => {
    const out = drawn({ action: "memory", learned: [{ ...saved, auto: true }] });
    expect(out).toContain("chat.mem_learned");
    expect(out).toContain("I hold for 5 years");
    expect(out).not.toContain("chat.mem_updated");
    expect(out).toContain("chat.mem_undo");
  });

  it("says one dropped unasked no longer applies", () => {
    const out = drawn({ learned: [{ ...saved, op: "deleted", auto: true }] });
    expect(out).toContain("chat.mem_dropped");
    expect(out).not.toContain("chat.mem_forgotten");
  });

  it("says a routine went on the daily action", () => {
    const routine = { ...saved, kind: "routine" };
    const asked = drawn({ action: "memory", learned: [routine] });
    expect(asked).toContain("chat.mem_routine_added");
    expect(asked).not.toContain("chat.mem_updated");
    const repeated = drawn({ learned: [{ ...routine, auto: true, repeated: 3 }] });
    expect(repeated).toContain("chat.mem_routine_repeated");
    expect(repeated).toContain("I hold for 5 years");
    expect(repeated).toContain("chat.mem_undo");
  });

  it("says a corrected memory was corrected, beside what it said before", () => {
    const out = drawn({ learned: [corrected] });
    expect(out).toContain("chat.mem_corrected");
    expect(out).toContain("I hold for 10 years");
    expect(out).toContain("ag-chat-memo-was");
    expect(out).toContain("chat.mem_undo");
  });

  it("undoes each change with the memory screen's inverse write", async () => {
    send.mockClear();
    await undoMemory(saved);
    await undoMemory(corrected);
    await undoMemory({ ...saved, op: "deleted" });
    expect(send.mock.calls).toEqual([
      ["DELETE", "/chat/memories/m1"],
      ["PATCH", "/chat/memories/m1", { text: "I hold for 5 years" }],
      ["POST", "/chat/memories", { text: "I hold for 5 years", kind: "goal" }],
    ]);
  });

  it("still says what was saved when the question after it was refused", () => {
    const out = drawn({ content: "", error: "chat.api_error", learned: [saved] });
    expect(out).toContain("chat.retry");
    expect(out).toContain("chat.mem_updated");
  });

  it("names the earlier conversations above the answer, closed until pressed", () => {
    const out = drawn({ recalled: [earlier] });
    expect(out).toContain("chat.recalled_one");
    expect(out).toContain("Nvidia");
    expect(out).toContain("We said NVDA was dear");
    expect(out).toMatch(/<ul class="ag-chat-recall-list"[^>]*hidden=""/);
    expect(out.indexOf("chat.recalled_one")).toBeLessThan(out.indexOf("Answer."));
  });

  it("counts several, and says so while the answer is still being written", () => {
    const out = drawn({
      content: "",
      pending: true,
      recalled: [earlier, { ...earlier, thread: "c_older" }],
    });
    expect(out).toContain("chat.recalled_n");
  });

  it("draws neither on a turn that had none", () => {
    const out = drawn({});
    expect(out).not.toContain("chat.recalled");
    expect(out).not.toContain("chat.mem_");
  });
});

describe("an answer's thumbs", () => {
  const answer = (over: Partial<Stored> = {}): Stored => ({
    role: "assistant",
    content: "SHOP rose on earnings.",
    skills: [],
    web: [],
    action: null,
    id: "a1b2c3",
    ...over,
  });

  it("draws both thumbs, unpressed, on a stored answer", () => {
    const out = drawTurn(answer());
    expect(out).toContain('aria-label="chat.rate_up"');
    expect(out).toContain('aria-label="chat.rate_down"');
    expect(out).not.toContain('aria-pressed="true"');
  });

  it("draws the stored vote pressed", () => {
    const out = drawTurn(answer({ rating: "down" }));
    expect(out.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(out).toContain("ag-chat-thumb-on");
  });

  it("is not offered where there is nothing to rate", () => {
    for (const turn of [
      answer({ id: undefined }),
      answer({ pending: true }),
      answer({ role: "user" }),
      answer({ guide: { step: "home" } }),
    ]) {
      expect(drawTurn(turn)).not.toContain("chat.rate_up");
    }
  });

  it("is drawn only on the turn the thread asks on", () => {
    expect(drawTurn(answer(), undefined, false)).not.toContain("chat.rate_up");
  });

  it("asks once per conversation, and only once something was answered", () => {
    const ask = (content: string): Stored => ({
      ...answer(),
      role: "user",
      content,
      id: undefined,
    });
    expect(rateAt([])).toBe(-1);
    expect(rateAt([ask("hola")])).toBe(-1);
    expect(rateAt([ask("hola"), answer({ pending: true })])).toBe(-1);
    // Until one is rated, the latest finished answer asks.
    const thread = [ask("a"), answer({ id: "x" }), ask("b"), answer({ id: "y" })];
    expect(rateAt(thread)).toBe(3);
    // A failed or still-streaming last turn leaves it on the one before.
    expect(
      rateAt([...thread, ask("c"), answer({ id: "z", error: "chat.api_error" })]),
    ).toBe(3);
    expect(
      rateAt([...thread, ask("c"), answer({ id: undefined, pending: true })]),
    ).toBe(3);
    // Once rated, that answer keeps it, however long the thread grows.
    const rated = [
      ask("a"),
      answer({ id: "x", rating: "up" }),
      ask("b"),
      answer({ id: "y" }),
    ];
    expect(rateAt(rated)).toBe(1);
    // The walkthrough's lines are never asked on.
    expect(rateAt([answer({ guide: { step: "home" } })])).toBe(-1);
  });

  it("is a PUT on the answer's id", async () => {
    const { rateTurn } = await import("./api");
    send.mockClear();
    await rateTurn("a/1", { vote: "down", reason: "made_up", note: "" });
    expect(send.mock.calls).toEqual([
      [
        "PUT",
        "/chat/turns/a%2F1/rating",
        { vote: "down", reason: "made_up", note: "" },
      ],
    ]);
  });
});

describe("an answer's sources", () => {
  const answered = (web: Stored["web"]): Stored => ({
    role: "assistant",
    content: "Answer.",
    skills: [],
    web,
    action: null,
  });

  it("opens an app document's screen in place and a web page in a new tab", () => {
    const html = drawTurn(
      answered([
        { title: "https://example.com/a", url: "https://example.com/a" },
        { title: "Spanish tax (IRPF)", url: "/portfolio?tab=tax", step: "tax" },
      ]),
    );
    expect(html).toContain("example.com</a>");
    expect(html).toMatch(
      /<a class="ag-chat-a" href="\/portfolio\?tab=tax">Spanish tax \(IRPF\)<\/a>/,
    );
    expect(html.match(/target="_blank"/g)).toHaveLength(1);
  });

  it("titles a tour step by its step and leaves a screenless document unlinked", () => {
    const html = drawTurn(
      answered([
        { title: "", url: "/import_transactions", step: "import" },
        { title: "What each part of TopStocks does", url: "", step: "" },
      ]),
    );
    expect(html).toContain('href="/import_transactions">');
    expect(html).toContain("<li><span>What each part of TopStocks does</span></li>");
  });
});
