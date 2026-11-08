/**
 * The one state machine behind both readings of the day's card: Home's teaser
 * (`GET/POST /daily`) and the Today page (`GET/POST /today`).
 *
 * - `read` takes what is stored and never writes. It paints at once.
 * - When the stored card no longer stands (a new day, a language switch, a
 *   computed card that can be upgraded) `write(false)` asks for it, once per
 *   action day: a re-render, or a second reading in the same tab, must not
 *   fire a second POST while the first is out. A failed write leaves the
 *   stored card up — the write is the extra.
 * - While the view wants it (`next`: the card `pending`, a market read a
 *   session behind) the flow reads again. One request at a time: the next is
 *   scheduled when the last has answered, and a failed one keeps what is on
 *   screen. A card still pending when `next` gives up is `stalled`.
 * - `regenerate` is `write(true)`: the old card goes the instant it is
 *   pressed, and the poll stands down until the server has the new job — a
 *   read answered before then would hand back the card just dismissed.
 *
 * Framework-free on purpose: the timers and the races are the hard part, and
 * they are tested here (cardFlow.test.ts) with fake timers rather than through
 * a page. `useCardFlow` is the thin React end.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { wantsWriting } from "./card";
import type { DailyCard } from "../home/types";

type FlowState<V> =
  | { kind: "loading" }
  | { kind: "failed" }
  /** `writing`: today's card has been asked for and is not on screen yet. */
  | { kind: "ready"; view: V; writing: boolean };

export type Snapshot<V> = { state: FlowState<V>; stalled: boolean };

export interface CardSource<V> {
  read(): Promise<V>;
  write(force: boolean): Promise<V>;
  /** The card in the view that may want writing; null when none may (a guest). */
  card(view: V): DailyCard | null;
  /** Milliseconds before reading again after `polls` reads; null stops. */
  next(view: V, polls: number): number | null;
  /** The view with its card wiped for a rewrite. */
  blank(view: V): V;
}

export interface CardFlow<V> {
  /** Read from the top with `source`, cancelling whatever was out. */
  load(source: CardSource<V>): void;
  /** Stop timers and drop answers still out (an unmount, a source change). */
  halt(): void;
  regenerate(): void;
  /** Read again from the top, asking for today's card anew (a brief changed). */
  restart(): void;
}

export function cardFlow<V>(emit: (snapshot: Snapshot<V>) => void): CardFlow<V> {
  let source: CardSource<V> | null = null;
  let state: FlowState<V> = { kind: "loading" };
  // Which action day has been asked for. Kept across loads, so a re-read does
  // not post again; `restart` forgets it.
  let asked: string | null = null;
  let posting = false;
  let polls = 0;
  // Bumped by every load and halt: an answer from an older generation is
  // dropped rather than painted over a newer reading.
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const stalled = (): boolean => {
    if (!source || state.kind !== "ready" || state.writing) return false;
    return (
      Boolean(source.card(state.view)?.pending) &&
      source.next(state.view, polls) === null
    );
  };

  const set = (next: FlowState<V>) => {
    state = next;
    emit({ state, stalled: stalled() });
  };

  const schedule = (gen: number) => {
    clearTimeout(timer);
    if (!source || gen !== generation) return;
    if (state.kind !== "ready" || state.writing) return;
    const delay = source.next(state.view, polls);
    if (delay === null) {
      // Settled: the next pending card starts a fresh count. Stalled keeps the
      // cap reached until the reader asks again.
      if (!stalled()) polls = 0;
      return;
    }
    const from = source;
    timer = setTimeout(() => {
      polls += 1;
      if (posting) {
        schedule(gen);
        return;
      }
      from.read().then(
        (view) => {
          if (gen !== generation) return;
          set({ kind: "ready", view, writing: false });
          schedule(gen);
        },
        () => schedule(gen),
      );
    }, delay);
  };

  const ready = (gen: number, view: V) => {
    if (gen !== generation) return;
    set({ kind: "ready", view, writing: false });
    schedule(gen);
  };

  const halt = () => {
    generation += 1;
    clearTimeout(timer);
  };

  const load = (next: CardSource<V>) => {
    halt();
    source = next;
    const gen = generation;
    polls = 0;
    set({ kind: "loading" });
    next
      .read()
      .then(async (view) => {
        if (gen !== generation) return;
        const card = next.card(view);
        if (!card || !wantsWriting(card, asked)) {
          ready(gen, view);
          return;
        }
        asked = card.action_day;
        set({ kind: "ready", view, writing: true });
        try {
          ready(gen, await next.write(false));
        } catch {
          ready(gen, view);
        }
      })
      .catch(() => {
        if (gen === generation) set({ kind: "failed" });
      });
  };

  const regenerate = () => {
    if (!source) return;
    const from = source;
    // A poll still out would land the card just dismissed over the blank one.
    halt();
    const gen = generation;
    posting = true;
    polls = 0;
    if (state.kind === "ready") set({ ...state, view: from.blank(state.view) });
    from
      .write(true)
      .finally(() => {
        posting = false;
      })
      .then(
        (view) => ready(gen, view),
        // Refused (rate limit, a dropped connection): put back whatever the
        // server says is current rather than leave the wait line up for good.
        () =>
          from.read().then(
            (view) => ready(gen, view),
            () => {
              if (gen === generation) set({ kind: "failed" });
            },
          ),
      );
  };

  const restart = () => {
    asked = null;
    if (source) load(source);
  };

  return { load, halt, regenerate, restart };
}

/**
 * The flow for a component. `source` is read whenever it changes, so the
 * caller memoises it on what it reads (the language, guest or not).
 */
export function useCardFlow<V>(source: CardSource<V>) {
  const [snapshot, setSnapshot] = useState<Snapshot<V>>({
    state: { kind: "loading" },
    stalled: false,
  });
  const flow = useRef<CardFlow<V> | null>(null);
  flow.current ??= cardFlow<V>(setSnapshot);

  useEffect(() => {
    const current = flow.current;
    current?.load(source);
    return () => current?.halt();
  }, [source]);

  const regenerate = useCallback(() => flow.current?.regenerate(), []);
  const restart = useCallback(() => flow.current?.restart(), []);
  return { ...snapshot, regenerate, restart };
}
