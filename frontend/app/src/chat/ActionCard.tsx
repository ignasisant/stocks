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
 */

import { useRef, useState } from "react";
import { useT } from "../shell/i18n";
import { Badge } from "../ui/Badge";
import { Status } from "../ui/Status";
import { Surface, type A2uiMessage } from "./a2ui";
import type { Edits, ToolCall } from "./types";

export function ActionCard({
  call,
  form,
  onDecide,
}: {
  call: ToolCall;
  /** The edit form's A2UI messages, when the server sent one. */
  form?: A2uiMessage[];
  /** Answer it; resolves with the refusal's key, or null when it went through. */
  onDecide?: (id: string, approved: boolean, edits?: Edits) => Promise<string | null>;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the form holds now, read on Confirm rather than kept in state: the
  // surface owns the typing, this card only needs the last value of it.
  const typed = useRef<Record<string, string> | null>(null);

  if (call.state === "done") return <Badge>{t("chat.action_done")}</Badge>;
  if (call.state === "cancelled") return <Badge>{t("chat.action_declined")}</Badge>;
  if (!onDecide) return null;

  const answer = async (approved: boolean) => {
    setSaving(true);
    setError(null);
    const edits =
      approved && editing && typed.current ? { form: typed.current } : undefined;
    const refused = await onDecide(call.id, approved, edits);
    setSaving(false);
    setError(refused);
  };

  return (
    <div className="ag-chat-act">
      {editing && form && (
        <Surface
          messages={form}
          disabled={saving}
          onData={(data) => {
            typed.current = (data.form as Record<string, string>) ?? null;
          }}
        />
      )}
      {error && <p className="ag-chat-hint ag-chat-act-error">{t(error)}</p>}
      {saving ? (
        <Status label={t("chat.action_working")} />
      ) : (
        <div className="ag-guide-acts">
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-on"
            onClick={() => void answer(true)}
          >
            {t("chat.action_approve")}
          </button>
          {!editing && form && (
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
