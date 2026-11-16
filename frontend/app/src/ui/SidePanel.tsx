/**
 * The one detail panel every page opens: a column at the right edge, full
 * height, on a desktop; a sheet from the bottom on a phone.
 *
 * A detail that unfolds inside its row pushes everything under it down by a
 * screen and reads at whatever width the row had. Here it reads at one width
 * and the list it came from stays in sight beside it. Portalled to the body:
 * `.ag-main` is a size container, and a container is the containing block of
 * a `position: fixed` inside it. Esc, the backdrop and Close all close; focus
 * goes to Close and back to whatever opened it. An open chat drawer moves the
 * panel left of itself (`chat.css`), so the chat beside it stays usable.
 *
 * The owner renders it while open and stops rendering it to close; the exit
 * runs from a ghost (`useExitGhost`), so there is nothing to keep mounted.
 */

import { type ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useDialog } from "../shell/useDialog";
import { useT } from "../shell/i18n";
import { useExitGhost } from "../shell/useSheet";
import "./ui.css";

export function SidePanel({
  label,
  head,
  onClose,
  children,
  className,
}: {
  /** The dialog's accessible name. */
  label: string;
  /** What sits left of Close: a title, a ticker cell. Defaults to `label`. */
  head?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const t = useT();
  const shut = useRef<HTMLButtonElement>(null);
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  useDialog(card, { initial: shut });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      ref={scrim}
      className="ag-panel"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={card}
        className={className ? `ag-panel-card ${className}` : "ag-panel-card"}
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        <div className="ag-panel-head">
          <div className="ag-panel-title">{head ?? <h2>{label}</h2>}</div>
          <button ref={shut} type="button" className="ag-panel-close" onClick={onClose}>
            {t("common.close")}
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
