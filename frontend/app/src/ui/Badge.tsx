/**
 * A label on something, not a figure and not a control: "in your portfolio",
 * "AI", "voice", the broker a position is held at.
 *
 * Six pages drew one each — sunken, outlined, page-toned, purple; pill here,
 * square there. Two looks are enough: `neutral` states a fact about the thing
 * it sits on, `brand` marks what the app itself produced (the AI briefing,
 * the Pulse read). A signed move is a `Chip`; a choice is a `ToggleChip`.
 */

import type { ReactNode } from "react";
import "./ui.css";

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "brand";
  title?: string;
}) {
  return (
    <span className={`ag-badge ag-badge-${tone}`} title={title}>
      {children}
    </span>
  );
}
