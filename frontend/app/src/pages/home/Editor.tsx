/**
 * Home's edit mode: put the cards in the order this reader reads them, put
 * some away, take others out of the tray.
 *
 * Loaded on demand (`lazy` in `Home.tsx`), so the drag library is paid for by
 * the reader who opens the editor and not by every Home visit.
 *
 * The cards are drawn as compact rows — a name and a line on what it shows —
 * rather than as themselves: a page of live tables is not something to drag,
 * and a row of a few dozen pixels is. Every move has a keyboard and a tap
 * route besides the drag: the arrows on each row, and dnd-kit's own keyboard
 * sensor on the handle.
 *
 * A screen reader hears every move (dnd-kit's announcements for a drag, a
 * live line for the arrows and the tray), and focus never drops to the page:
 * a card put away hands it to its "Add" in the tray, and back.
 *
 * Nothing is written until "Done". A layout identical to the default is saved
 * as null, so a reader who resets keeps following the default as it changes.
 */

import { useEffect, useRef, useState } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Icon } from "../../shell/Icon";
import {
  HOME_CARDS,
  defaultLayout,
  moveSlot,
  sameLayout,
  toggleSlot,
  type CardId,
  type Slot,
} from "./cards";
import { Card, Note } from "./ui";

/** Spelled out so the catalog keys are greppable. */
const TEXT: Record<CardId, { name: string; blurb: string }> = {
  market: { name: "home.card_market", blurb: "home.card_market_blurb" },
  daily: { name: "home.card_daily", blurb: "home.card_daily_blurb" },
  glance: { name: "home.card_glance", blurb: "home.card_glance_blurb" },
  movers: { name: "home.card_movers", blurb: "home.card_movers_blurb" },
  extremes: { name: "home.card_extremes", blurb: "home.card_extremes_blurb" },
  earnings: { name: "home.card_earnings", blurb: "home.card_earnings_blurb" },
  transactions: {
    name: "home.card_transactions",
    blurb: "home.card_transactions_blurb",
  },
  watchlist: { name: "home.card_watchlist", blurb: "home.card_watchlist_blurb" },
  risk: { name: "home.card_risk", blurb: "home.card_risk_blurb" },
  dividends: { name: "home.card_dividends", blurb: "home.card_dividends_blurb" },
  tax: { name: "home.card_tax", blurb: "home.card_tax_blurb" },
  rotation: { name: "home.card_rotation", blurb: "home.card_rotation_blurb" },
};

const known = new Set<string>(HOME_CARDS.map((card) => card.id));

/** Shown first, in order, then the tray: the shape the editor works on. */
function split(layout: readonly Slot[]): Slot[] {
  const cards = layout.filter((slot) => known.has(slot.id));
  return [...cards.filter((slot) => !slot.hidden), ...cards.filter((s) => s.hidden)];
}

export default function Editor({
  layout,
  onClose,
}: {
  layout: Slot[];
  /** `saved` is the layout now stored (null: the default), or undefined on cancel. */
  onClose: (saved?: Slot[] | null) => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState<Slot[]>(() => split(layout));
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  // What a screen reader hears after an arrow, a hide or an add.
  const [said, setSaid] = useState("");
  // The control to focus once the row it lives in has re-rendered.
  const [focus, setFocus] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const sensors = useSensors(
    // A few pixels of travel before a press becomes a drag, so a tap on the
    // handle is still a tap.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // The editor replaces the page under the button that opened it: its
  // heading takes focus, or focus would fall to the document.
  useEffect(() => {
    root.current?.querySelector<HTMLElement>(".hm-edit-title")?.focus();
  }, []);

  useEffect(() => {
    if (!focus) return;
    root.current?.querySelector<HTMLElement>(`[data-focus="${focus}"]`)?.focus();
    setFocus(null);
  }, [focus]);

  const shown = draft.filter((slot) => !slot.hidden);
  const tray = draft.filter((slot) => slot.hidden);
  const nameOf = (id: UniqueIdentifier) => {
    const text = TEXT[String(id) as CardId];
    return text ? t(text.name) : String(id);
  };
  const place = (active: UniqueIdentifier, over: UniqueIdentifier) => ({
    name: nameOf(active),
    n: shown.findIndex((slot) => slot.id === over) + 1,
    total: shown.length,
  });

  const announcements: Announcements = {
    onDragStart: ({ active }) => t("home.edit_picked", { name: nameOf(active.id) }),
    onDragOver: ({ active, over }) =>
      over ? t("home.edit_moved", place(active.id, over.id)) : undefined,
    onDragEnd: ({ active, over }) =>
      over ? t("home.edit_dropped", place(active.id, over.id)) : undefined,
    onDragCancel: ({ active }) =>
      t("home.edit_drag_cancel", { name: nameOf(active.id) }),
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = draft.findIndex((slot) => slot.id === active.id);
    const to = draft.findIndex((slot) => slot.id === over.id);
    setDraft(moveSlot(draft, from, to));
  };

  const move = (id: string, at: number, step: -1 | 1) => {
    const next = moveSlot(draft, at, at + step);
    setDraft(next);
    const n = next.findIndex((slot) => slot.id === id) + 1;
    setSaid(t("home.edit_moved", { name: nameOf(id), n, total: shown.length }));
  };

  const hide = (id: string) => {
    setDraft(toggleSlot(draft, id));
    setSaid(t("home.edit_hidden", { name: nameOf(id) }));
    setFocus(`add-${id}`);
  };

  const add = (id: string) => {
    setDraft(toggleSlot(draft, id));
    setSaid(t("home.edit_added", { name: nameOf(id) }));
    setFocus(`hide-${id}`);
  };

  const done = () => {
    if (sameLayout(split(layout), draft)) {
      onClose(undefined);
      return;
    }
    const value = sameLayout(split(defaultLayout()), draft) ? null : draft;
    setSaving(true);
    setFailed(false);
    send("PATCH", "/prefs", { home_layout: value }).then(
      () => onClose(value),
      () => {
        setSaving(false);
        setFailed(true);
      },
    );
  };

  return (
    <div ref={root}>
      <Card className="hm-editor">
        <h2 className="hm-card-title hm-edit-title" tabIndex={-1}>
          {t("home.edit_title")}
        </h2>
        <Note>{t("home.edit_hint")}</Note>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements,
            screenReaderInstructions: { draggable: t("home.edit_instructions") },
          }}
        >
          <SortableContext
            items={shown.map((slot) => slot.id)}
            strategy={verticalListSortingStrategy}
          >
            <ol className="hm-edit-list">
              {shown.map((slot, i) => (
                <Row
                  key={slot.id}
                  id={slot.id as CardId}
                  first={i === 0}
                  last={i === shown.length - 1}
                  onMove={(step) => move(slot.id, i, step)}
                  onHide={() => hide(slot.id)}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
        {tray.length > 0 ? (
          <>
            <h3 className="hm-caption hm-edit-tray-title">{t("home.edit_tray")}</h3>
            <ul className="hm-edit-list hm-edit-tray">
              {tray.map((slot) => {
                const name = nameOf(slot.id);
                return (
                  <li key={slot.id} className="hm-edit-row">
                    <span className="hm-edit-text">
                      <strong>{name}</strong>
                      <span className="hm-caption">
                        {t(TEXT[slot.id as CardId].blurb)}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="hm-edit-btn"
                      data-focus={`add-${slot.id}`}
                      aria-label={t("home.edit_add_named", { name })}
                      onClick={() => add(slot.id)}
                    >
                      <Icon name="add" size={16} />
                      {t("home.edit_add")}
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}
        <p className="ag-sr" aria-live="polite">
          {said}
        </p>
        <div role="alert">{failed ? <Note>{t("home.edit_failed")}</Note> : null}</div>
        <div className="hm-edit-actions">
          <button
            type="button"
            className="ag-btn"
            disabled={saving}
            onClick={() => {
              setDraft(split(defaultLayout()));
              setSaid(t("home.edit_reset_done"));
            }}
          >
            {t("home.edit_reset")}
          </button>
          <span className="hm-edit-spacer" />
          <button
            type="button"
            className="ag-btn"
            disabled={saving}
            onClick={() => onClose(undefined)}
          >
            {t("home.edit_cancel")}
          </button>
          <button
            type="button"
            className="ag-btn hm-btn-primary"
            disabled={saving}
            aria-busy={saving}
            onClick={done}
          >
            {t("home.edit_done")}
          </button>
        </div>
      </Card>
    </div>
  );
}

function Row({
  id,
  first,
  last,
  onMove,
  onHide,
}: {
  id: CardId;
  first: boolean;
  last: boolean;
  onMove: (step: -1 | 1) => void;
  onHide: () => void;
}) {
  const t = useT();
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, transition: { duration: 150, easing: "ease-out" } });
  const text = TEXT[id];
  const name = t(text.name);
  return (
    <li
      ref={setNodeRef}
      className={isDragging ? "hm-edit-row hm-edit-dragging" : "hm-edit-row"}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        className="hm-edit-handle"
        {...attributes}
        {...listeners}
        aria-label={t("home.edit_drag", { name })}
      >
        <Icon name="drag_indicator" size={18} />
      </button>
      <span className="hm-edit-text">
        <strong>{name}</strong>
        <span className="hm-caption">{t(text.blurb)}</span>
      </span>
      <span className="hm-edit-tools">
        {/* aria-disabled rather than disabled: the arrow that just took its
            row to the top would otherwise switch off under focus and drop it
            to the page. */}
        <button
          type="button"
          className="hm-edit-icon"
          aria-disabled={first}
          aria-label={t("home.edit_up", { name })}
          onClick={() => (first ? undefined : onMove(-1))}
        >
          <Icon name="arrow_upward" size={16} />
        </button>
        <button
          type="button"
          className="hm-edit-icon"
          aria-disabled={last}
          aria-label={t("home.edit_down", { name })}
          onClick={() => (last ? undefined : onMove(1))}
        >
          <Icon name="arrow_downward" size={16} />
        </button>
        <button
          type="button"
          className="hm-edit-btn"
          data-focus={`hide-${id}`}
          aria-label={t("home.edit_hide_named", { name })}
          onClick={onHide}
        >
          {t("home.edit_hide")}
        </button>
      </span>
    </li>
  );
}
