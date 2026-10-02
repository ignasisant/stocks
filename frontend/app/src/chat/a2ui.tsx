/**
 * An A2UI surface (a2ui.org, v0.9), drawn from the server's messages.
 *
 * A surface is data: a flat list of components by id, from a catalog this
 * file carries, bound by JSON Pointer to a data model the inputs write into.
 * Nothing in it runs — a component this catalog does not have draws nothing,
 * text is text, and the only thing a press can do is hand an action back to
 * whoever mounted the surface. That is what lets the server grow a card (a
 * proposal's fields, an import's column mapping, a what-if) without a
 * component written for each.
 *
 * The catalog is `stocks/chat/a2ui.py`'s, which builds every surface the
 * server sends and is held to this one by `tests/test_chat_a2ui.py`: the
 * basic catalog's layout and inputs, plus Aguait's `Metric` (the KPI readout),
 * `Ticker` (a symbol with its logo and its link — every ticker on screen is
 * one), `Chart` (closes the server fetched, drawn as a line: `chart.tsx`) and
 * `Donut` (the book's weights the server summed: `donut.tsx`), and a `Slider`
 * and a `ChoicePicker` that send their `action` when the reader lets go of
 * the one or picks from the other.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { TickerCell } from "../shell/tickers";
import { Kpi, type Tone } from "../ui/Kpi";
import { ToggleChip, ToggleRow } from "../ui/Toggle";
import { type Line, LineChart } from "./chart";
import { AllocationDonut } from "./donut";

type Component = { id: string; component: string } & Record<string, unknown>;

/** One A2UI v0.9 server message. Only the four this drawer reads are typed. */
export type A2uiMessage = {
  version: string;
  createSurface?: { surfaceId: string; catalogId: string; sendDataModel?: boolean };
  updateComponents?: { surfaceId: string; components: Component[] };
  updateDataModel?: { surfaceId: string; path?: string; value: unknown };
  deleteSurface?: { surfaceId: string };
};

/** A press, as A2UI's client-to-server action message carries it. */
export type A2uiAction = {
  name: string;
  surfaceId: string;
  sourceComponentId: string;
  timestamp: string;
  context: Record<string, unknown>;
};

type Data = Record<string, unknown>;

/** JSON Pointer segments, `~1` and `~0` unescaped. "" and "/" are the root. */
const segments = (pointer: string) =>
  pointer
    .split("/")
    .slice(1)
    .filter((part, i, all) => part !== "" || i < all.length - 1)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));

function read(data: unknown, pointer: string): unknown {
  let here: unknown = data;
  for (const key of segments(pointer)) {
    if (here === null || typeof here !== "object") return undefined;
    here = (here as Record<string, unknown>)[key];
  }
  return here;
}

/** `data` with `value` at `pointer`, copied along the way — never mutated. */
function write(data: unknown, pointer: string, value: unknown): unknown {
  const keys = segments(pointer);
  if (!keys.length) return value;
  const [head, ...rest] = keys as [string, ...string[]];
  const here =
    data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  const next = rest.length ? write(here[head], `/${rest.join("/")}`, value) : value;
  return Array.isArray(here)
    ? Object.assign([...here], { [head]: next })
    : { ...here, [head]: next };
}

const isBinding = (value: unknown): value is { path: string } =>
  !!value &&
  typeof value === "object" &&
  typeof (value as { path?: unknown }).path === "string";

/** A dynamic value: a literal, or `{ path }` read from the data model. */
const resolve = (value: unknown, data: Data): unknown =>
  isBinding(value) ? read(data, value.path) : value;

/** An action's context, every binding in it read. One level deep, as A2UI's is. */
const context = (raw: unknown, data: Data): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries((raw as Record<string, unknown>) ?? {}).map(([k, v]) => [
      k,
      resolve(v, data),
    ]),
  );

/** The messages folded into one surface: its id, its parts, its first data. */
function fold(messages: A2uiMessage[]) {
  let surfaceId = "";
  const parts = new Map<string, Component>();
  let data: unknown = {};
  for (const message of messages) {
    if (message.createSurface) surfaceId = message.createSurface.surfaceId;
    for (const part of message.updateComponents?.components ?? [])
      parts.set(part.id, part);
    const update = message.updateDataModel;
    if (update) data = write(data, update.path ?? "", update.value);
    if (message.deleteSurface) parts.clear();
  }
  return { surfaceId, parts, data: (data ?? {}) as Data };
}

type Draw = {
  part: Component;
  data: Data;
  child: (id: string) => ReactNode;
  set: (pointer: string, value: unknown) => void;
  /**
   * Hand an action to the caller, its context read from `data` — or from
   * `next`, when the press that fires it also wrote the value it sends.
   */
  fire: (action: unknown, next?: Data) => void;
  disabled: boolean;
};

const str = (value: unknown) =>
  value === undefined || value === null ? "" : String(value);

function Field({ part, data, set, disabled }: Draw) {
  const bound = isBinding(part.value) ? part.value.path : "";
  const number = part.variant === "number";
  return (
    <label className="ag-a2ui-field">
      <span>{str(resolve(part.label, data))}</span>
      <input
        className="ag-chat-input"
        value={str(resolve(part.value, data))}
        inputMode={number ? "decimal" : "text"}
        disabled={disabled || !bound}
        onChange={(event) => bound && set(bound, event.target.value)}
      />
    </label>
  );
}

type Option = { label: unknown; value: unknown };

/**
 * A choice drawn as a row of chips, one press each: the variant for a few
 * short options the reader flips between, a chart's windows. With an `action`,
 * a press sends it at once — there is nothing to confirm about picking "5Y".
 */
function Chips({ part, data, set, fire, disabled }: Draw) {
  const bound = isBinding(part.value) ? part.value.path : "";
  const options = (Array.isArray(part.options) ? part.options : []) as Option[];
  const picked = str(resolve(part.value, data));
  return (
    <ToggleRow
      className="ag-a2ui-chips"
      label={part.label === undefined ? undefined : str(resolve(part.label, data))}
    >
      {options.map((option) => {
        const value = str(option.value);
        return (
          <ToggleChip
            key={value}
            on={value === picked}
            disabled={disabled || !bound}
            onClick={() => {
              if (!bound || value === picked) return;
              set(bound, value);
              if (part.action) fire(part.action, write(data, bound, value) as Data);
            }}
          >
            {str(resolve(option.label, data))}
          </ToggleChip>
        );
      })}
    </ToggleRow>
  );
}

function Picker(draw: Draw) {
  const { part, data, set, disabled } = draw;
  if (part.variant === "chips") return <Chips {...draw} />;
  const bound = isBinding(part.value) ? part.value.path : "";
  const options = (Array.isArray(part.options) ? part.options : []) as Option[];
  return (
    <label className="ag-a2ui-field">
      {part.label !== undefined && <span>{str(resolve(part.label, data))}</span>}
      <select
        className="ag-chat-select"
        value={str(resolve(part.value, data))}
        disabled={disabled || !bound}
        onChange={(event) => bound && set(bound, event.target.value)}
      >
        {options.map((option) => (
          <option key={str(option.value)} value={str(option.value)}>
            {str(resolve(option.label, data))}
          </option>
        ))}
      </select>
    </label>
  );
}

function Range({ part, data, set, fire, disabled }: Draw) {
  const bound = isBinding(part.value) ? part.value.path : "";
  const value = Number(resolve(part.value, data) ?? part.min ?? 0);
  // Sent on release, not on every step of a drag: each one is a server
  // round trip, and the reader is choosing a value, not scrubbing through all
  // of them.
  const commit = () => part.action && fire(part.action);
  return (
    <label className="ag-a2ui-field ag-a2ui-slider">
      {part.label !== undefined && (
        <span>
          {str(resolve(part.label, data))} <strong>{value}</strong>
        </span>
      )}
      <input
        type="range"
        min={Number(part.min)}
        max={Number(part.max)}
        step={part.step === undefined ? 1 : Number(part.step)}
        value={Number.isFinite(value) ? value : 0}
        disabled={disabled || !bound}
        onChange={(event) => bound && set(bound, Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
      />
    </label>
  );
}

const TONES: Tone[] = ["up", "down", "warn", "flat"];

/**
 * What this drawer can draw, by A2UI component name. Anything else is
 * skipped: a surface from a newer server degrades to the parts this one has.
 */
const CATALOG: Record<string, (draw: Draw) => ReactNode> = {
  Column: ({ part, child }) => (
    <div className="ag-a2ui-col">
      {((part.children as string[]) ?? []).map((id) => (
        <div key={id}>{child(id)}</div>
      ))}
    </div>
  ),
  Row: ({ part, child }) => (
    <div className={`ag-a2ui-row ag-a2ui-align-${str(part.align) || "start"}`}>
      {((part.children as string[]) ?? []).map((id) => (
        <div key={id}>{child(id)}</div>
      ))}
    </div>
  ),
  Text: ({ part, data }) => (
    <p className={`ag-a2ui-text ag-a2ui-${str(part.variant) || "body"}`}>
      {str(resolve(part.text, data))}
    </p>
  ),
  Divider: () => <hr className="ag-a2ui-divider" />,
  TextField: (draw) => <Field {...draw} />,
  ChoicePicker: (draw) => <Picker {...draw} />,
  CheckBox: ({ part, data, set, disabled }) => {
    const bound = isBinding(part.value) ? part.value.path : "";
    return (
      <label className="ag-chat-check">
        <input
          type="checkbox"
          checked={!!resolve(part.value, data)}
          disabled={disabled || !bound}
          onChange={(event) => bound && set(bound, event.target.checked)}
        />
        {str(resolve(part.label, data))}
      </label>
    );
  },
  Slider: (draw) => <Range {...draw} />,
  Button: ({ part, data, fire, disabled }) => (
    <button
      type="button"
      className={
        part.variant === "primary" ? "ag-chat-btn ag-chat-btn-on" : "ag-chat-btn"
      }
      disabled={disabled}
      onClick={() => part.action && fire(part.action)}
    >
      {str(resolve(part.text, data))}
    </button>
  ),
  Metric: ({ part, data }) => {
    const tone = str(resolve(part.tone, data)) as Tone;
    return (
      <Kpi
        label={str(resolve(part.label, data))}
        value={str(resolve(part.value, data))}
        valueTone={TONES.includes(tone) ? tone : null}
        note={part.hint === undefined ? null : str(resolve(part.hint, data))}
      />
    );
  },
  Ticker: ({ part, data }) => {
    const symbol = str(resolve(part.symbol, data)).toUpperCase();
    return symbol ? <TickerCell ticker={symbol} /> : null;
  },
  Chart: ({ part, data }) => {
    const series = resolve(part.series, data);
    return Array.isArray(series) && series.length ? (
      <LineChart
        series={series as Line[]}
        rebased={part.mode === "change"}
        label={str(resolve(part.label, data))}
      />
    ) : null;
  },
  // `slices` is one split, or every split keyed by name with `by` naming the
  // one drawn — a chips picker bound to `by` then switches it in place.
  Donut: ({ part, data }) => {
    const groups = resolve(part.slices, data);
    const by = str(resolve(part.by, data));
    const slices = Array.isArray(groups)
      ? groups
      : groups && typeof groups === "object"
        ? (groups as Record<string, unknown>)[by]
        : undefined;
    return Array.isArray(slices) && slices.length ? (
      <AllocationDonut
        slices={slices as { label: string; weight: number }[]}
        label={str(resolve(part.label, data))}
        other={str(resolve(part.other, data))}
      />
    ) : null;
  },
};

export function Surface({
  messages,
  onAction,
  onData,
  disabled = false,
}: {
  messages: A2uiMessage[];
  /** A press. Absent: the buttons are drawn and do nothing. */
  onAction?: (action: A2uiAction) => void;
  /** The data model after every edit — what a caller sends back on its own press. */
  onData?: (data: Data) => void;
  /** While the caller is busy with the last press. */
  disabled?: boolean;
}) {
  const folded = useMemo(() => fold(messages), [messages]);
  const [data, setData] = useState<Data>(folded.data);
  // New messages are a new surface (or new data for this one): what the
  // server says replaces what was typed into the last one.
  useEffect(() => setData(folded.data), [folded]);
  const told = useRef(onData);
  told.current = onData;
  useEffect(() => told.current?.(data), [data]);

  const drawing = new Set<string>();
  const child = (id: string): ReactNode => {
    const part = folded.parts.get(id);
    // A part that contains itself would draw forever; A2UI's adjacency list
    // makes that expressible, so it is refused here.
    if (!part || drawing.has(id)) return null;
    const draw = CATALOG[part.component];
    if (!draw) return null;
    drawing.add(id);
    const out = draw({
      part,
      data,
      child,
      disabled,
      set: (pointer, value) => setData((was) => write(was, pointer, value) as Data),
      fire: (action, next) => {
        const event = (action as { event?: { name?: string; context?: unknown } })
          .event;
        if (!event?.name || !onAction) return;
        onAction({
          name: event.name,
          surfaceId: folded.surfaceId,
          sourceComponentId: part.id,
          timestamp: new Date().toISOString(),
          context: context(event.context, next ?? data),
        });
      },
    });
    drawing.delete(id);
    return out;
  };

  return <div className="ag-a2ui">{child("root")}</div>;
}
