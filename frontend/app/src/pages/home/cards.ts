/**
 * Which cards Home can draw, and in what order this reader asked for them.
 *
 * The registry is the default page: its order is the running order a new
 * account gets, and `optional` cards start in the "add" tray rather than on
 * the page. What the reader changed is stored as a list of `{id, hidden}` in
 * `prefs.home_layout` — the server checks its shape and nothing else, so the
 * registry lives here alone and an id the client no longer knows is simply
 * dropped when the layout is read.
 *
 * A card that ships after somebody saved a layout has no slot in it.
 * `resolveLayout` puts it where the default order would — after the nearest
 * card that precedes it there — so a new card turns up where a new account
 * would see it instead of at the bottom, and an optional one turns up hidden.
 */

type Span = "full" | "half";

export type CardId =
  | "market"
  | "daily"
  | "glance"
  | "movers"
  | "extremes"
  | "earnings"
  | "transactions"
  | "watchlist"
  | "risk"
  | "dividends"
  | "tax"
  | "rotation";

export type CardSpec = {
  id: CardId;
  /** Half cards pair up two to a row on a wide page; a lone one runs full. */
  span: Span;
  /** Off the page until the reader adds it. */
  optional: boolean;
  /** Somebody's own data: a guest neither sees it nor gets it offered. */
  signedIn: boolean;
};

/** One stored entry. `id` is a string because a stored one may be stale. */
export type Slot = { id: string; hidden: boolean };

export const HOME_CARDS: readonly CardSpec[] = [
  { id: "market", span: "full", optional: false, signedIn: false },
  { id: "daily", span: "full", optional: false, signedIn: true },
  { id: "glance", span: "full", optional: false, signedIn: true },
  { id: "movers", span: "half", optional: false, signedIn: true },
  { id: "extremes", span: "half", optional: false, signedIn: false },
  { id: "earnings", span: "full", optional: false, signedIn: false },
  { id: "transactions", span: "half", optional: false, signedIn: true },
  { id: "watchlist", span: "full", optional: false, signedIn: false },
  { id: "risk", span: "half", optional: true, signedIn: true },
  { id: "dividends", span: "half", optional: true, signedIn: true },
  { id: "tax", span: "half", optional: true, signedIn: true },
  { id: "rotation", span: "half", optional: true, signedIn: false },
];

/** The page a new account gets, as slots. */
export function defaultLayout(registry: readonly CardSpec[] = HOME_CARDS): Slot[] {
  return registry.map((card) => ({ id: card.id, hidden: card.optional }));
}

/**
 * The stored layout read against the registry: every registry card exactly
 * once, in the reader's order, unknown and repeated ids gone.
 */
export function resolveLayout(
  stored: readonly Slot[] | null | undefined,
  registry: readonly CardSpec[] = HOME_CARDS,
): Slot[] {
  if (!stored || stored.length === 0) return defaultLayout(registry);
  const known = new Set<string>(registry.map((card) => card.id));
  const out: Slot[] = [];
  const seen = new Set<string>();
  for (const slot of stored) {
    if (!known.has(slot.id) || seen.has(slot.id)) continue;
    seen.add(slot.id);
    out.push({ id: slot.id, hidden: slot.hidden === true });
  }
  registry.forEach((card, index) => {
    if (seen.has(card.id)) return;
    let at = 0;
    for (let before = index - 1; before >= 0; before--) {
      const id = registry[before]?.id;
      const found = out.findIndex((slot) => slot.id === id);
      if (found >= 0) {
        at = found + 1;
        break;
      }
    }
    out.splice(at, 0, { id: card.id, hidden: card.optional });
    seen.add(card.id);
  });
  return out;
}

/** The cards to draw, in order: shown, and a guest's to see. */
export function visibleCards(
  layout: readonly Slot[],
  guest: boolean,
  registry: readonly CardSpec[] = HOME_CARDS,
): CardSpec[] {
  const byId = new Map(registry.map((card) => [card.id as string, card]));
  return layout.flatMap((slot) => {
    const card = byId.get(slot.id);
    if (!card || slot.hidden || (guest && card.signedIn)) return [];
    return [card];
  });
}

/** Whether two layouts draw the same page — "Done" with nothing changed saves nothing. */
export function sameLayout(a: readonly Slot[], b: readonly Slot[]): boolean {
  return (
    a.length === b.length &&
    a.every((slot, i) => slot.id === b[i]?.id && slot.hidden === b[i]?.hidden)
  );
}

/** Move the slot at `from` to `to`, as a new list. */
export function moveSlot(layout: readonly Slot[], from: number, to: number): Slot[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= layout.length ||
    to >= layout.length
  ) {
    return [...layout];
  }
  const next = [...layout];
  next.splice(to, 0, ...next.splice(from, 1));
  return next;
}

/** Hide or show one card, as a new list. A card shown again goes to the end. */
export function toggleSlot(layout: readonly Slot[], id: string): Slot[] {
  const at = layout.findIndex((slot) => slot.id === id);
  if (at < 0) return [...layout];
  if (layout[at]?.hidden) {
    const rest = layout.filter((_, i) => i !== at);
    const lastShown = rest.reduce((last, s, i) => (s.hidden ? last : i), -1);
    rest.splice(lastShown + 1, 0, { id, hidden: false });
    return rest;
  }
  return layout.map((s, i) => (i === at ? { id, hidden: true } : s));
}

/**
 * The layout this tab last saved, over the session's copy.
 *
 * The session's prefs are read once when the app opens, and reloading them
 * repaints the whole shell, so a save here does not ask for that. Navigating
 * away and back would then draw the layout the app opened with; this is the
 * newer word until the next full load replaces both.
 */
let saved: { layout: Slot[] | null } | null = null;

export function rememberLayout(layout: Slot[] | null): void {
  saved = { layout };
}

export function storedLayout(fromSession: Slot[] | null | undefined): Slot[] | null {
  return saved ? saved.layout : (fromSession ?? null);
}
