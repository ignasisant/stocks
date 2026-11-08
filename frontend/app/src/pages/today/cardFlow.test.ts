import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DailyCard } from "../home/types";
import { cardFlow, type CardSource, type Snapshot } from "./cardFlow";

function card(over: Partial<DailyCard> = {}): DailyCard {
  return {
    day: "2026-09-24",
    headline: "Two names carry the week",
    bullets: [],
    focus: [],
    as_of: "2026-09-23",
    lang: "en",
    source: "llm",
    action_day: "2026-09-24",
    fresh: true,
    generated: null,
    pending: false,
    items: [],
    upgradable: false,
    analysed: [],
    ...over,
  };
}

/** A promise settled from the test, for answers that land out of order. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const CAP = 3;

function source(over: Partial<CardSource<DailyCard>> = {}): CardSource<DailyCard> {
  return {
    read: vi.fn(() => Promise.resolve(card())),
    write: vi.fn(() => Promise.resolve(card())),
    card: (view) => view,
    next: (view, polls) => (view.pending && polls < CAP ? 1000 : null),
    blank: (view) => ({ ...view, headline: null, pending: true }),
    ...over,
  };
}

function run() {
  const seen: Snapshot<DailyCard>[] = [];
  const flow = cardFlow<DailyCard>((s) => seen.push(s));
  const last = () => seen[seen.length - 1]!;
  return { flow, seen, last };
}

const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("cardFlow", () => {
  it("paints a card that stands without writing", async () => {
    const { flow, last } = run();
    const src = source();
    flow.load(src);
    expect(last().state.kind).toBe("loading");
    await flush();
    expect(last().state).toMatchObject({ kind: "ready", writing: false });
    expect(src.write).not.toHaveBeenCalled();
  });

  it("asks once per action day for a card that no longer stands", async () => {
    const { flow, seen, last } = run();
    const written = card({ headline: "Today's" });
    const src = source({
      read: vi.fn(() => Promise.resolve(card({ fresh: false }))),
      write: vi.fn(() => Promise.resolve(written)),
    });
    flow.load(src);
    await flush();
    expect(seen.some((s) => s.state.kind === "ready" && s.state.writing)).toBe(true);
    expect(last().state).toEqual({ kind: "ready", view: written, writing: false });
    expect(src.write).toHaveBeenCalledWith(false);

    // A second reading of the same stale card does not post again...
    flow.load(src);
    await flush();
    expect(src.write).toHaveBeenCalledTimes(1);
    // ...until the reader asks for the day anew.
    flow.restart();
    await flush();
    expect(src.write).toHaveBeenCalledTimes(2);
  });

  it("keeps the stored card up when the write fails", async () => {
    const { flow, last } = run();
    const stored = card({ fresh: false });
    flow.load(
      source({
        read: () => Promise.resolve(stored),
        write: () => Promise.reject(new Error("429")),
      }),
    );
    await flush();
    expect(last().state).toEqual({ kind: "ready", view: stored, writing: false });
  });

  it("fails when the first read does", async () => {
    const { flow, last } = run();
    flow.load(source({ read: () => Promise.reject(new Error("500")) }));
    await flush();
    expect(last().state.kind).toBe("failed");
  });

  it("never writes when the view has no card of the reader's", async () => {
    const { flow } = run();
    const src = source({
      read: () => Promise.resolve(card({ fresh: false })),
      card: () => null,
    });
    flow.load(src);
    await flush();
    expect(src.write).not.toHaveBeenCalled();
  });

  it("polls one read at a time while pending, then stops", async () => {
    const { flow, last } = run();
    const answers = [card({ pending: true }), card({ pending: true }), card()];
    const read = vi.fn(() => Promise.resolve(answers.shift() ?? card()));
    flow.load(source({ read }));
    await flush();
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);
    expect(read).toHaveBeenCalledTimes(3);
    expect(last().state).toMatchObject({ view: { pending: false } });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(read).toHaveBeenCalledTimes(3);
  });

  it("keeps what is on screen when a poll fails, and polls again", async () => {
    const { flow, last } = run();
    const pending = card({ pending: true, headline: "Computed" });
    const read = vi
      .fn<() => Promise<DailyCard>>()
      .mockResolvedValueOnce(pending)
      .mockRejectedValueOnce(new Error("drop"))
      .mockResolvedValue(card());
    flow.load(source({ read }));
    await flush();
    await vi.advanceTimersByTimeAsync(1000);
    expect(last().state).toMatchObject({ kind: "ready", view: pending });
    await vi.advanceTimersByTimeAsync(1000);
    expect(read).toHaveBeenCalledTimes(3);
    expect(last().state).toMatchObject({ view: { pending: false } });
  });

  it("calls a card still pending at the cap stalled until the reader restarts", async () => {
    const { flow, last } = run();
    const read = vi.fn(() => Promise.resolve(card({ pending: true })));
    flow.load(source({ read }));
    await flush();
    await vi.advanceTimersByTimeAsync(1000 * CAP);
    expect(read).toHaveBeenCalledTimes(1 + CAP);
    expect(last().stalled).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(read).toHaveBeenCalledTimes(1 + CAP);

    flow.restart();
    await flush();
    expect(last().stalled).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(read).toHaveBeenCalledTimes(3 + CAP);
  });

  it("does not call a settled card stalled", async () => {
    const { flow, last } = run();
    flow.load(source({ next: () => null }));
    await flush();
    expect(last().stalled).toBe(false);
  });

  it("blanks the card on regenerate and lands the rewrite", async () => {
    const { flow, last } = run();
    const out = deferred<DailyCard>();
    const fresh = card({ headline: "Rewritten" });
    const src = source({ write: vi.fn(() => out.promise) });
    flow.load(src);
    await flush();
    flow.regenerate();
    expect(last().state).toMatchObject({ view: { headline: null, pending: true } });
    expect(src.write).toHaveBeenCalledWith(true);
    out.resolve(fresh);
    await flush();
    expect(last().state).toEqual({ kind: "ready", view: fresh, writing: false });
  });

  it("drops a poll still out when regenerate is pressed", async () => {
    const { flow, last } = run();
    const poll = deferred<DailyCard>();
    const old = card({ pending: true, headline: "Old" });
    const read = vi
      .fn<() => Promise<DailyCard>>()
      .mockResolvedValueOnce(old)
      .mockReturnValueOnce(poll.promise);
    const rewrite = deferred<DailyCard>();
    flow.load(source({ read, write: () => rewrite.promise }));
    await flush();
    await vi.advanceTimersByTimeAsync(1000);
    expect(read).toHaveBeenCalledTimes(2);
    flow.regenerate();
    poll.resolve(old);
    await flush();
    expect(last().state).toMatchObject({ view: { headline: null } });
    // Nor does it poll while its own write is out.
    await vi.advanceTimersByTimeAsync(5000);
    expect(read).toHaveBeenCalledTimes(2);
    rewrite.resolve(card({ headline: "New" }));
    await flush();
    expect(last().state).toMatchObject({ view: { headline: "New" } });
  });

  it("puts back the server's card when a regenerate is refused", async () => {
    const { flow, last } = run();
    const current = card({ headline: "Current" });
    const read = vi
      .fn<() => Promise<DailyCard>>()
      .mockResolvedValueOnce(card())
      .mockResolvedValueOnce(current);
    flow.load(source({ read, write: () => Promise.reject(new Error("429")) }));
    await flush();
    flow.regenerate();
    await flush();
    expect(last().state).toEqual({ kind: "ready", view: current, writing: false });
  });

  it("drops an answer from a reading it moved on from", async () => {
    const { flow, last } = run();
    const first = deferred<DailyCard>();
    const second = card({ headline: "Spanish" });
    const read = vi
      .fn<() => Promise<DailyCard>>()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(second);
    const src = source({ read });
    flow.load(src);
    flow.load({ ...src });
    await flush();
    first.resolve(card({ headline: "English" }));
    await flush();
    expect(last().state).toMatchObject({ view: { headline: "Spanish" } });
  });

  it("stops polling once halted", async () => {
    const { flow } = run();
    const read = vi.fn(() => Promise.resolve(card({ pending: true })));
    flow.load(source({ read }));
    await flush();
    flow.halt();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(read).toHaveBeenCalledTimes(1);
  });
});
