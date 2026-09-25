/**
 * What the two repairs share: how a proposal is named, and how a reader says
 * which ones they believe.
 *
 * Both apply routes take named proposals and never "all", and that is the point
 * rather than an inconvenience: the evidence is per holding, so believing it is
 * too. A split is named by ticker and date; a move is named by the ledger ids
 * the scan handed back, because two equal parcels of one security leaving the
 * same broker on the same day differ in nothing a name could carry.
 */

import { useState } from "react";
import type { Move, SplitGap } from "./api";

export const splitKey = (gap: SplitGap): string => `${gap.ticker}|${gap.date}`;

export const moveKey = (move: Move): string =>
  `${[...move.out_ids].sort((a, b) => a - b).join(",")}|${move.in_id ?? ""}`;

/**
 * "20:1" for a 20-for-1 split — the ratio as the Streamlit page prints it
 * (`f"{ratio:g}:1"`), which is a shape and not a measured figure, so it is not
 * localised and not padded.
 */
export const ratioLabel = (ratio: number): string => `${ratio}:1`;

/** Same comparison the server makes on a typed confirmation: trimmed, folded. */
export function names(typed: string, email: string): boolean {
  return (
    email.trim() !== "" && typed.trim().toLowerCase() === email.trim().toLowerCase()
  );
}

/**
 * Which proposals are ticked.
 *
 * Everything starts ticked — the page this replaces applies the lot with one
 * button, and a scan that came back with nothing selected would ask the reader
 * to do the work twice. What is remembered is therefore what they *un*ticked,
 * so a fresh scan offers its new findings on rather than off.
 */
export function useSelection(keys: string[]) {
  const [off, setOff] = useState<ReadonlySet<string>>(new Set());
  return {
    on: (key: string) => !off.has(key),
    picked: keys.filter((key) => !off.has(key)),
    toggle: (key: string) =>
      setOff((previous) => {
        const next = new Set(previous);
        if (!next.delete(key)) next.add(key);
        return next;
      }),
  };
}
