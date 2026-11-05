/**
 * The share dialog: a title, whatever the thing being shared shows of itself
 * (`children`), then where to send it (`ShareOut`). The answer's sheet
 * (`chat/ShareSheet.tsx`) is one with a preview and a link to make first; a
 * ticker or an invite has its link already and opens straight onto the out.
 *
 * Portalled to the body like every dialog: a dialog drawn inside the chat
 * drawer, a fixed panel, would be clipped to its width.
 */

import { createPortal } from "react-dom";
import { useEffect, useRef, type ReactNode } from "react";
import { Glyph } from "../chat/icons";
import { useT } from "../shell/i18n";
import { useDialog } from "../shell/useDialog";
import { useExitGhost } from "../shell/useSheet";
import { ShareOut } from "./ShareOut";
import "./share.css";

export function ShareDialog({
  title,
  url,
  text,
  onClose,
  linkLabel,
  children,
  footer,
}: {
  title: string;
  /** The link, once there is one; nothing to send until then. */
  url: string | null;
  text: string;
  /** What the link field is called to a screen reader. */
  linkLabel?: string;
  onClose: () => void;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const t = useT();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const scrim = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  const card = useRef<HTMLDivElement>(null);
  const shut = useRef<HTMLButtonElement>(null);
  useDialog(card, { initial: shut });

  return createPortal(
    <div
      ref={scrim}
      className="ag-share-scrim"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={card}
        className="ag-share"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="ag-share-head">
          <h2 className="ag-share-title">{title}</h2>
          <button
            ref={shut}
            type="button"
            className="ag-chat-icon"
            title={t("chat.close")}
            aria-label={t("chat.close")}
            onClick={onClose}
          >
            <Glyph name="close" size={18} />
          </button>
        </div>
        {children}
        {url ? <ShareOut url={url} text={text} label={linkLabel} /> : null}
        {footer}
      </div>
    </div>,
    document.body,
  );
}
