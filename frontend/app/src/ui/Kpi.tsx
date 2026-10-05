/**
 * The KPI tile, its grid, its chip and its "?" — one shape for every page.
 *
 * Before this file every page drew its own tile: Home on the page ground,
 * Portfolio sunken with an uppercase label, the ticker page two ways, the
 * earnings dialog and the Pulse book two more. Same idea, six looks, so a
 * figure read differently depending on where it was. A page now composes
 * these and styles none of them; `ui.css` is the only place the tile's look
 * is written down.
 *
 * The slots, top to bottom: `label` (+ `help`), `value` (+ `chip` beside it),
 * `note` under it, and `children` for anything the domain adds — a meter, a
 * sparkline. Every slot but the first two is optional, and an empty one takes
 * no room: a chip with no text is not drawn, so a caller hands over whatever
 * `chipFor` returned and never writes the `null` check itself.
 */

import {
  type ReactNode,
  useCallback,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTouchHold } from "../shell/useTouchHold";
import "./ui.css";

/**
 * What a chip or a figure says with colour.
 *
 * `up` / `down` are a signed move; `warn` is the domain's amber band (the
 * fundamentals' "orange"); `flat` is everything that should not be coloured —
 * unknown, zero, or a figure that is real but not live.
 */
export type Tone = "up" | "down" | "warn" | "flat";

export type ChipSpec = { text: string; tone: Tone };

/** Sign of a figure as a tone. `null`, `NaN` and zero are `flat`. */
export function toneOf(value: number | null | undefined): Tone {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) {
    return "flat";
  }
  return value > 0 ? "up" : "down";
}

/**
 * A signed figure as a chip, or null when there is nothing to say.
 *
 * `off` greys the chip instead of colouring it by sign: for a figure that is
 * real but not live — outside a session the day change is the last completed
 * one, and colouring it green implies something is moving right now.
 */
export function chipFor(
  value: number | null | undefined,
  text: string | null | undefined,
  off = false,
): ChipSpec | null {
  if (!text || value === null || value === undefined) return null;
  return { text, tone: off ? "flat" : toneOf(value) };
}

/**
 * The domain's band colour (`analysis.fundamentals`: green / orange / red /
 * gray) as a tone, so a verdict chip is coloured by the band the API sends and
 * never by matching on its label.
 */
export function bandTone(band: string | null | undefined): Tone {
  if (band === "green") return "up";
  if (band === "red") return "down";
  if (band === "orange") return "warn";
  return "flat";
}

/** The pill. Draws nothing when handed nothing. */
export function Chip({ chip }: { chip: ChipSpec | null | undefined }) {
  if (!chip || !chip.text) return null;
  return <span className={`ag-chip ag-chip-${chip.tone}`}>{chip.text}</span>;
}

/** Breathing room kept between the popover and the viewport edge, in px. */
const HELP_MARGIN = 8;

/**
 * How far to slide a popover sideways so it sits inside the viewport. Positive
 * pushes it right (it overran the left edge), negative pulls it left. When the
 * panel is wider than the room, the left edge wins: the start of a sentence is
 * the part that has to be readable.
 */
export function helpShift(left: number, right: number, viewport: number): number {
  if (left < HELP_MARGIN) return HELP_MARGIN - left;
  if (right > viewport - HELP_MARGIN) {
    return Math.max(viewport - HELP_MARGIN - right, HELP_MARGIN - left);
  }
  return 0;
}

/**
 * The definition marker beside a label.
 *
 * It used to ride a native `title`, which a phone cannot show: no hover, so
 * the definition behind every tile was simply unreachable. It is a button now
 * — a tap opens the text under the mark, a tap anywhere else or Escape puts it
 * away (`useTouchHold` is the same "touch elsewhere" dismissal the charts
 * use), and a mouse still gets it on hover or keyboard focus. The panel is
 * measured once it is up and slid back inside the viewport, since a tile's
 * mark can sit at either edge of a 390px screen. The 14px mark keeps its
 * footprint; the finger-sized hit area is a pseudo-element in `ui.css`.
 */
export function Help({ text }: { text: string | null | undefined }) {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const [shift, setShift] = useState(0);
  const wrap = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLSpanElement>(null);
  const id = useId();
  const unpin = useCallback(() => setPinned(false), []);
  useTouchHold(wrap, pinned, unpin);

  const shown = pinned || hover;
  useLayoutEffect(() => {
    if (!shown || !panel.current) return;
    // Measure from the unshifted position, so a re-open never compounds.
    const rect = panel.current.getBoundingClientRect();
    const unshifted = { left: rect.left - shift, right: rect.right - shift };
    setShift(helpShift(unshifted.left, unshifted.right, window.innerWidth));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, text]);

  if (!text) return null;
  return (
    <span
      className="ag-kpi-help-wrap"
      ref={wrap}
      onPointerEnter={(event) => event.pointerType === "mouse" && setHover(true)}
      onPointerLeave={() => setHover(false)}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setPinned(false);
          setHover(false);
        }
      }}
    >
      <button
        type="button"
        className="ag-kpi-help"
        aria-expanded={pinned}
        aria-describedby={shown ? id : undefined}
        aria-label={text}
        onClick={() => setPinned((open) => !open)}
        onFocus={(event) =>
          event.currentTarget.matches(":focus-visible") && setHover(true)
        }
        onBlur={() => setHover(false)}
      >
        ?
      </button>
      {shown && (
        <span
          className="ag-kpi-help-pop"
          id={id}
          role="tooltip"
          ref={panel}
          style={{ transform: `translateX(${shift}px)` }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

/**
 * A row of tiles. Rows of two, three, four and six wrap evenly rather than
 * leaving an orphan — `ui.css` counts the tiles actually drawn.
 */
export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="ag-kpis">{children}</div>;
}

export function Kpi({
  label,
  value,
  chip,
  help,
  note,
  noteTone,
  valueTone,
  children,
}: {
  label: ReactNode;
  /** Already formatted. The caller decides what "no figure" reads as. */
  value: ReactNode;
  chip?: ChipSpec | null;
  help?: string | null;
  /** One muted line under the figure — a conversion, a share count. */
  note?: ReactNode;
  noteTone?: Tone | null;
  /** Colour the figure itself — for a P/L that has no chip to carry its sign. */
  valueTone?: Tone | null;
  /** Anything the domain draws under the figure: a meter, a sparkline. */
  children?: ReactNode;
}) {
  return (
    <div className="ag-kpi">
      <div className="ag-kpi-head">
        <span className="ag-kpi-label">{label}</span>
        <Help text={help} />
      </div>
      <div className="ag-kpi-row">
        <span
          className={valueTone ? `ag-kpi-value ag-tone-${valueTone}` : "ag-kpi-value"}
        >
          {value}
        </span>
        <Chip chip={chip} />
      </div>
      {note ? (
        <span className={noteTone ? `ag-kpi-note ag-tone-${noteTone}` : "ag-kpi-note"}>
          {note}
        </span>
      ) : null}
      {children}
    </div>
  );
}
