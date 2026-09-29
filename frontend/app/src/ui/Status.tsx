/**
 * The ticking line that says something the reader asked for is being done.
 *
 * Everything a press waits on draws one — an answer, a statement being read
 * or written, a voice note being transcribed, a ledger being wiped. A control
 * that only goes disabled tells the reader nothing: it looks broken, and on a
 * phone the disabled state barely reads at all.
 *
 * A status rather than a plain line: it is the only thing that tells a screen
 * reader the press was taken, and it is announced now rather than held back
 * with whatever it is waiting on.
 */

import "./ui.css";

export function Status({ label }: { label: string }) {
  return (
    <div className="ag-work" role="status">
      <span className="ag-work-glyph" aria-hidden="true">
        ✻
      </span>
      {label}
    </div>
  );
}
