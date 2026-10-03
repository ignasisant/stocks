/**
 * The drawer's half of the AG-UI wire: the run it sends and the events it reads.
 *
 * `run` is the one fetch the drawer parses itself, so this is where a change in
 * the server's framing would first stop an answer from landing. The stream here
 * is written the way the server writes it — `data:` lines, the type inside the
 * JSON — and split at awkward places, because that is how a network hands it
 * over.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { run, runInput } from "./api";

function stream(events: object[], cut = 7): Response {
  const body =
    ": open\n\n" + events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const bytes = new TextEncoder().encode(body);
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < bytes.length; i += cut)
          controller.enqueue(bytes.slice(i, i + cut));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("the run the drawer sends", () => {
  it("carries only the new message, and where the reader is", () => {
    const input = runInput(
      { message: "is it cheap?" },
      {
        conversation: "c_1",
        lang: "es",
        view: "ticker",
        focus: "NVDA",
        staged_import: "x.csv",
      },
    );
    expect(input.threadId).toBe("c_1");
    expect(input.messages).toEqual([
      { id: expect.any(String), role: "user", content: "is it cheap?" },
    ]);
    expect(input.state).toEqual({ view: "ticker", focus: "NVDA" });
    expect(input.forwardedProps).toEqual({ lang: "es", staged_import: "x.csv" });
    expect(input.tools?.map((tool) => tool.name)).toEqual(["navigate"]);
    expect(input.resume).toBeUndefined();
  });

  it("answers a proposal with no message at all", () => {
    const input = runInput(
      { resume: { interruptId: "act_1", status: "cancelled" } },
      { staged_import: "x.csv" },
    );
    expect(input.messages).toEqual([]);
    expect(input.resume).toEqual([{ interruptId: "act_1", status: "cancelled" }]);
    expect(input.forwardedProps).toEqual({});
  });
});

describe("the events it reads", () => {
  it("hands over the steps, the meta and the words, and ends on the result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          { type: "RUN_STARTED", threadId: "c_1", runId: "r" },
          { type: "STEP_STARTED", stepName: "gathering" },
          { type: "STEP_FINISHED", stepName: "gathering" },
          {
            type: "CUSTOM",
            name: "chat.meta",
            value: { provider: "free", model: "m", skills: [], sources: [] },
          },
          { type: "TEXT_MESSAGE_START", messageId: "m1", role: "assistant" },
          { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Look at " },
          { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "tax." },
          { type: "TEXT_MESSAGE_END", messageId: "m1" },
          { type: "TOOL_CALL_START", toolCallId: "nav_1", toolCallName: "navigate" },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "nav_1",
            delta: '{"page": "portfolio",',
          },
          { type: "TOOL_CALL_ARGS", toolCallId: "nav_1", delta: ' "tab": "tax"}' },
          { type: "TOOL_CALL_END", toolCallId: "nav_1" },
          {
            type: "RUN_FINISHED",
            threadId: "c_1",
            runId: "r",
            result: {
              text: "Look at tax.",
              skills: [],
              sources: [],
              provider: "free",
              steps: [],
            },
          },
        ]),
      ),
    );
    const phases: string[] = [];
    const chunks: string[] = [];
    const metas: string[] = [];
    const done = await run(
      runInput({ message: "hola" }, {}),
      (meta) => metas.push(meta.provider),
      (chunk) => chunks.push(chunk),
      (phase) => phases.push(phase),
    );
    expect(phases).toEqual(["gathering"]);
    expect(metas).toEqual(["free"]);
    expect(chunks.join("")).toBe("Look at tax.");
    expect(done.text).toBe("Look at tax.");
    expect(done.error).toBeNull();
    expect(done.calls).toEqual([
      { id: "nav_1", name: "navigate", args: { page: "portfolio", tab: "tax" } },
    ]);
  });

  it("marks the call a run was interrupted on as pending", async () => {
    const proposal = {
      id: "act_1",
      kind: "favorite",
      ticker: "AAPL",
      args: {},
      state: "pending",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          {
            type: "TOOL_CALL_START",
            toolCallId: "act_1",
            toolCallName: "confirm_action",
          },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "act_1",
            delta: '{"kind": "favorite", "ticker": "AAPL", "args": {}}',
          },
          { type: "TOOL_CALL_END", toolCallId: "act_1" },
          {
            type: "RUN_FINISHED",
            threadId: "c",
            runId: "r",
            result: { text: "Add?", proposal },
            outcome: {
              type: "interrupt",
              interrupts: [{ id: "act_1", reason: "confirm_action" }],
            },
          },
        ]),
      ),
    );
    const done = await run(
      runInput({ message: "fav AAPL" }, {}),
      () => {},
      () => {},
      () => {},
    );
    expect(done.calls[0]).toMatchObject({ id: "act_1", state: "pending" });
    expect(done.proposal).toEqual(proposal);
  });

  it("reads a run error as its locale key, and a cut stream as a failed one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([{ type: "RUN_ERROR", message: "x", code: "chat.free_exhausted" }]),
      ),
    );
    const refused = await run(
      runInput({ message: "hola" }, {}),
      () => {},
      () => {},
      () => {},
    );
    expect(refused.error).toBe("chat.free_exhausted");

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream([{ type: "RUN_STARTED" }])),
    );
    const cut = await run(
      runInput({ message: "hola" }, {}),
      () => {},
      () => {},
      () => {},
    );
    expect(cut.error).toBe("chat.api_error");
  });

  it("hands over the recalled conversations early, and a memory change even on a refusal", async () => {
    const earlier = [
      { thread: "c_0", title: "Nvidia", when: "2026-09-01T00:00:00Z", snippet: "dear" },
    ];
    const learned = [{ op: "added", id: "m1", text: "I hold 5y", kind: "goal" }];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          { type: "CUSTOM", name: "chat.recalled", value: earlier },
          { type: "CUSTOM", name: "chat.learned", value: learned },
          { type: "RUN_ERROR", message: "x", code: "chat.free_exhausted" },
        ]),
      ),
    );
    const seen: unknown[] = [];
    const refused = await run(
      runInput({ message: "remember that I hold 5y. is NVDA dear?" }, {}),
      () => {},
      () => {},
      () => {},
      undefined,
      undefined,
      undefined,
      (recalled) => seen.push(recalled),
    );
    expect(seen).toEqual([earlier]);
    expect(refused.error).toBe("chat.free_exhausted");
    expect(refused.learned).toEqual(learned);
  });

  it("tells the research as it runs, and keeps it out of the answer's calls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          { type: "STEP_STARTED", stepName: "gathering" },
          { type: "TOOL_CALL_START", toolCallId: "tool_1", toolCallName: "search_web" },
          {
            type: "TOOL_CALL_ARGS",
            toolCallId: "tool_1",
            delta: '{"query": "nvidia   guidance"}',
          },
          { type: "TOOL_CALL_END", toolCallId: "tool_1" },
          {
            type: "TOOL_CALL_RESULT",
            messageId: "res_1",
            toolCallId: "tool_1",
            role: "tool",
            content: "5 results",
          },
          { type: "RUN_FINISHED", threadId: "c", runId: "r", result: { text: "ok" } },
        ]),
      ),
    );
    const lines: object[] = [];
    const done = await run(
      runInput({ message: "nvidia?" }, {}),
      () => {},
      () => {},
      () => {},
      undefined,
      (line) => lines.push(line),
    );
    expect(lines).toEqual([
      { id: "tool_1", tool: "search_web", arg: "nvidia guidance" },
      { id: "tool_1", tool: "search_web", arg: "nvidia guidance", out: "5 results" },
    ]);
    expect(done.calls).toEqual([]);
  });

  it("keeps a subagent's words out of the answer and hands them to its side", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          { type: "SUBAGENT_STARTED", subagentRunId: "sub_bull", name: "bull" },
          {
            type: "TEXT_MESSAGE_START",
            messageId: "msg_sub",
            role: "assistant",
            subagentRunId: "sub_bull",
          },
          {
            type: "TEXT_MESSAGE_CONTENT",
            messageId: "msg_sub",
            delta: "- cash flow",
            subagentRunId: "sub_bull",
          },
          { type: "TEXT_MESSAGE_END", messageId: "msg_sub", subagentRunId: "sub_bull" },
          { type: "SUBAGENT_FINISHED", subagentRunId: "sub_bull" },
          { type: "SUBAGENT_STARTED", subagentRunId: "sub_bear", name: "bear" },
          {
            type: "SUBAGENT_ERROR",
            subagentRunId: "sub_bear",
            code: "chat.debate_failed",
          },
          { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Verdict." },
          {
            type: "RUN_FINISHED",
            threadId: "c",
            runId: "r",
            result: {
              text: "Verdict.",
              debate: [{ side: "bull", text: "- cash flow" }],
            },
          },
        ]),
      ),
    );
    const chunks: string[] = [];
    const sides: { side: string; state: string; text: string }[] = [];
    const done = await run(
      runInput({ message: "should I buy?" }, {}),
      () => {},
      (chunk) => chunks.push(chunk),
      () => {},
      undefined,
      undefined,
      (side) => sides.push({ side: side.side, state: side.state, text: side.text }),
    );
    expect(chunks).toEqual(["Verdict."]);
    expect(sides.at(-1)).toEqual({ side: "bear", state: "failed", text: "" });
    expect(sides.filter((s) => s.side === "bull").at(-1)).toEqual({
      side: "bull",
      state: "done",
      text: "- cash flow",
    });
    expect(done.debate).toEqual([{ side: "bull", text: "- cash flow" }]);
  });
});
