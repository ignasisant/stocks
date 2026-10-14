/**
 * What a modal owes the keyboard: focus goes in when it opens, Tab stays
 * inside it, and focus goes back to what opened it when it closes.
 *
 * `aria-modal` only tells a screen reader the page behind is inert; it moves
 * no focus and stops no Tab, so without this a keyboard reader pressed Tab
 * straight out of the tour into the page it covers. Escape and the scrim stay
 * with each dialog, because what they *mean* differs (the tour parks, the
 * welcome and the profile prompt close).
 *
 * Focus lands on the dialog itself (`tabIndex={-1}`), not its first button: a
 * screen reader then reads the dialog's name, and Enter cannot fire the
 * leading action by accident on a modal the reader did not ask for. A dialog
 * the reader opened to act in passes `initial` instead — the field to type in,
 * or the Close a reader paging through a list wants under their finger. One
 * that stays mounted and shows on a flag passes `open`.
 */

import { type RefObject, useEffect } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useDialog(
  ref: RefObject<HTMLElement | null>,
  {
    initial,
    open = true,
  }: { initial?: RefObject<HTMLElement | null>; open?: boolean } = {},
): void {
  useEffect(() => {
    const el = ref.current;
    if (!open || !el) return;
    const before = document.activeElement as HTMLElement | null;
    (initial?.current ?? el).focus({ preventScroll: true });

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) {
        event.preventDefault();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === el)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (!el.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };
    el.addEventListener("keydown", onKey);
    return () => {
      el.removeEventListener("keydown", onKey);
      // Only if focus was left on the dialog (or nowhere): a click that moved
      // it to the page the dialog sent the reader to is not ours to undo.
      const now = document.activeElement;
      if (before?.isConnected && (!now || now === document.body || el.contains(now))) {
        before.focus({ preventScroll: true });
      }
    };
  }, [ref, initial, open]);
}
