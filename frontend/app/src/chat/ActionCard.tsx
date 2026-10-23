/**
 * A proposal: an app action the assistant asks about before it runs.
 *
 * AG-UI's human in the loop. The run that detected "add AAPL to favourites"
 * finished *interrupted* on a `confirm_action` call instead of writing the
 * watchlist, and this card is how the reader answers it: Confirm runs it,
 * Edit opens the values the classifier read so a misheard price or the wrong
 * symbol is fixed before anything is written, Cancel drops it. The drawer
 * used to act first and confirm afterwards, which left a misread instruction
 * already applied by the time anyone saw it.
 *
 * The fields under Edit are not this file's: they are an A2UI surface the
 * server built from the tool registry (`chat/a2ui.py`'s `proposal_form`), so
 * a tool that gains a field gains it here without a line of TypeScript.
 * Confirm sends that surface's `/form` back as the interrupt's answer.
 *
 * The bubble above holds the question; the card holds only the controls, and
 * once answered, where the proposal ended up. Typing "yes" under it does the
 * same as pressing Confirm (the server settles it), and the card follows.
 *
 * A ledger edit (`args.book`, from `chat/book.py`) has no Edit: it was planned
 * against the book on the server and commits exactly as the figures above it
 * say. Once done it offers Undo, which takes the change back through the
 * book's journal.
 *
 * A reported trade missing a figure (`args.book.fill`: "he vendido S a 26,51")
 * opens on its form instead, preset with what was said, and Review — live
 * once every field reads (`tradeReady`) — sends it:
 * the server plans the trade and this same card comes back as that ledger
 * edit, its figures above and Confirm under them.
 */

import { useRef, useState } from "react";
import { useT } from "../shell/i18n";
import { Badge } from "../ui/Badge";
import { Status } from "../ui/Status";
import { toast } from "../ui/toast";
import { Surface, type A2uiMessage } from "./a2ui";
import type { Edits, ToolCall } from "./types";

/**
 * Whether a trade form is whole: a side, shares and a price above zero, a day.
 * Review waits for it — the server would refuse anything less
 * (`tools.trade_args`), and a round trip to say "fill it in" is one too many.
 */
export function tradeReady(form: Record<string, string> | null): boolean {
  if (!form) return false;
  const figure = (raw: string | undefined) => Number((raw ?? "").replace(",", "."));
  return (
    (form.trade === "buy" || form.trade === "sell") &&
    figure(form.quantity) > 0 &&
    figure(form.price) > 0 &&
    /^\d{4}-\d{2}-\d{2}$/.test(form.date ?? "")
  );
}

export function ActionCard({
  call,
  form,
  onDecide,
  onUndo,
}: {
  call: ToolCall;
  /** The edit form's A2UI messages, when the server sent one. */
  form?: A2uiMessage[];
  /** Answer it; resolves with the refusal's key, or null when it went through. */
  onDecide?: (id: string, approved: boolean, edits?: Edits) => Promise<string | null>;
  /** Take back a ledger edit once done; resolves like `onDecide`. */
  onUndo?: (id: string) => Promise<string | null>;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  // What the form holds now, read on Confirm rather than kept in state: the
  // surface owns the typing, this card only needs the last value of it.
  const typed = useRef<Record<string, string> | null>(null);
  const [ready, setReady] = useState(false);

  const book = call.args.book as { change?: number | null; fill?: unknown } | undefined;
  const filling = !!book?.fill;
  if (call.state === "undone") return <Badge>{t("chat.action_undone")}</Badge>;
  if (call.state === "done") {
    if (!book?.change || !onUndo) return <Badge>{t("chat.action_done")}</Badge>;
    const takeBack = async () => {
      setSaving(true);
      const refused = await onUndo(call.id);
      setSaving(false);
      if (refused) toast.bad(t(refused));
    };
    return (
      <div className="ag-chat-act">
        {saving ? (
          <Status label={t("chat.action_working")} />
        ) : (
          <div className="ag-guide-acts">
            <Badge>{t("chat.action_done")}</Badge>
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => void takeBack()}
            >
              {t("chat.action_undo")}
            </button>
          </div>
        )}
      </div>
    );
  }
  if (call.state === "cancelled") return <Badge>{t("chat.action_declined")}</Badge>;
  if (!onDecide) return null;

  const answer = async (approved: boolean) => {
    setSaving(true);
    const edits =
      approved && (editing || filling) && typed.current
        ? { form: typed.current }
        : undefined;
    const refused = await onDecide(call.id, approved, edits);
    setSaving(false);
    if (refused) toast.bad(t(refused));
  };

  return (
    <div className="ag-chat-act">
      {(editing || filling) && form && (
        <Surface
          messages={form}
          disabled={saving}
          onData={(data) => {
            typed.current = (data.form as Record<string, string>) ?? null;
            setReady(tradeReady(typed.current));
          }}
        />
      )}
      {saving ? (
        <Status label={t("chat.action_working")} />
      ) : (
        <div className="ag-guide-acts">
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-on"
            disabled={filling && !ready}
            onClick={() => void answer(true)}
          >
            {t(filling ? "chat.action_review" : "chat.action_approve")}
          </button>
          {!editing && form && !book && (
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => setEditing(true)}
            >
              {t("chat.action_edit")}
            </button>
          )}
          <button
            type="button"
            className="ag-chat-btn"
            onClick={() => void answer(false)}
          >
            {t("chat.action_cancel")}
          </button>
        </div>
      )}
    </div>
  );
}
