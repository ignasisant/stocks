/**
 * A text box with its controls inside it, and the microphone that lives there.
 *
 * The chat's composer and the feedback dialog both take dictation, and they
 * draw the microphone the same way in the same place: inside the box, bottom
 * right, where the thumb is when a line ends. The reader asked for exactly
 * that (feedback, 2026-09-29) after finding it beside the paperclip in one and
 * as a text button under the box in the other — and two copies of one control
 * drift, which is how they came to differ.
 *
 * The box only lays the controls over the field's corner; the field pads
 * itself clear of them (`ag-box`), so a long line wraps before it runs under
 * a button.
 */

import type { ReactNode } from "react";

import { Glyph } from "../chat/icons";
import "./ui.css";

export function Box({ children, tools }: { children: ReactNode; tools: ReactNode }) {
  return (
    <div className="ag-box">
      {children}
      <div className="ag-box-tools">{tools}</div>
    </div>
  );
}

/**
 * Press to record, press again to stop. Critical while it is listening,
 * because nothing else on screen says the device is open.
 */
export function Mic({
  on,
  disabled,
  label,
  onPress,
}: {
  on: boolean;
  disabled?: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <button
      type="button"
      className={on ? "ag-box-tool ag-box-rec" : "ag-box-tool"}
      disabled={disabled}
      aria-pressed={on}
      title={label}
      aria-label={label}
      onClick={onPress}
    >
      <Glyph name={on ? "stop" : "mic"} size={18} />
    </button>
  );
}
