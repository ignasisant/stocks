/**
 * A pasted screenshot, opened at the size it can be read at.
 *
 * Over a sent question the picture is a thumbnail: it says which screenshot
 * this was. Checking a figure in it against the answer needs the picture
 * itself, and the drawer is a third of a screen wide. So one press opens it
 * over the page, whole: fitted to the window, and never larger than what was
 * on the screen when it was taken. A capture holds `devicePixelRatio` pixels
 * per point, so drawn pixel for pixel it comes out twice the size of the
 * page it is a picture of, and cropped by the window. A press on the picture
 * is the way to that size, for a table too dense to read fitted.
 *
 * Portalled to the body like every dialog: drawn inside the chat drawer, a
 * fixed panel, it would be clipped to the drawer's width.
 */

import { createPortal } from "react-dom";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useT } from "../shell/i18n";
import { useDialog } from "../shell/useDialog";
import { useExitGhost } from "../shell/useSheet";
import { Glyph } from "./icons";

/** The scrim's padding and the card's border, both sides (`chat.css`). */
const FRAME = 34;
/** A small crop is not shrunk below this to match the screen it came from:
 *  at half its pixels it would open no larger than its own thumbnail. */
const SMALL = 480;

export function ShotView({ url, onClose }: { url: string; onClose: () => void }) {
  const t = useT();
  const [zoomed, setZoomed] = useState(false);
  const [size, setSize] = useState<{ w: number; h: number }>();
  const pic = useRef<HTMLImageElement>(null);
  const measure = () => {
    const img = pic.current;
    if (img?.naturalWidth) setSize({ w: img.naturalWidth, h: img.naturalHeight });
  };
  // The thumbnail has already decoded this picture, so it is usually measured
  // before the first paint; `onLoad` is for when it is not.
  useLayoutEffect(measure, [url]);
  const ratio = window.devicePixelRatio || 1;
  const more =
    size !== undefined &&
    (ratio > 1 ||
      size.w > window.innerWidth - FRAME ||
      size.h > window.innerHeight - FRAME);
  const img = (
    <img
      ref={pic}
      src={url}
      alt={t("chat.shot_alt")}
      onLoad={measure}
      style={
        size
          ? ({
              "--shot-fit": `${Math.max(size.w / ratio, Math.min(size.w, SMALL))}px`,
            } as CSSProperties)
          : undefined
      }
    />
  );

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
      className="ag-chat-shotview-scrim"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={card}
        className="ag-chat-shotview"
        role="dialog"
        aria-modal="true"
        aria-label={t("chat.shot_alt")}
        tabIndex={-1}
      >
        <button
          ref={shut}
          type="button"
          className="ag-chat-icon ag-chat-shotview-x"
          title={t("chat.close")}
          aria-label={t("chat.close")}
          onClick={onClose}
        >
          <Glyph name="close" size={18} />
        </button>
        <div className="ag-chat-shotview-pic" data-zoomed={zoomed || undefined}>
          {more ? (
            <button
              type="button"
              className="ag-chat-shotview-zoom"
              aria-pressed={zoomed}
              title={t(zoomed ? "chat.shot_fit" : "chat.shot_zoom_in")}
              aria-label={t(zoomed ? "chat.shot_fit" : "chat.shot_zoom_in")}
              onClick={() => setZoomed((was) => !was)}
            >
              {img}
            </button>
          ) : (
            img
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
