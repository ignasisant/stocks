/**
 * Sharing one answer by link: what the link would show, then where to send it.
 *
 * The preview comes first and is the server's own cut (`preview: true`), not
 * a guess drawn here: amounts hidden, the proposals and the tables of money
 * gone, the charts inert. "Hide my amounts" starts on — an answer about a
 * portfolio quotes it, and the safe link is the one that needs no thought.
 * Turning it off asks for the other cut, which the preview then shows.
 *
 * Nothing is published until "Create link". The same answer cut the same way
 * is the same link, so pressing it again on an answer already shared shows
 * the link it went out under rather than minting a second one.
 *
 * Then the destinations. A phone's own share sheet first, where there is one
 * (`navigator.share` — WhatsApp, Telegram, Messages, whatever the reader has),
 * and the main platforms as plain links everywhere, because the desktop sheet
 * is thin and a link to wa.me is a link everyone's browser can follow. The URL
 * carries `src=share`, so a signup it leads to is credited (`attribution.py`).
 *
 * Portalled to the body like every dialog: the drawer is a fixed panel, and a
 * dialog drawn inside it would be clipped to its width.
 */

import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { useT } from "../shell/i18n";
import { useDialog } from "../shell/useDialog";
import { useExitGhost } from "../shell/useSheet";
import { Status } from "../ui/Status";
import { shareTurn, unshare } from "./api";
import { Glyph } from "./icons";
import { SharedBody } from "./SharedPanel";
import type { SharedAnswer, ShareLink } from "./types";

/**
 * The message is the sharer's own voice on the question ("I asked TopStocks'
 * AI: …"): on X the card is an image and a domain, so the post's text is all
 * that says what the link is. Past this the question is cut on a word.
 */
const TEXT_MAX = 100;

export function shareUrl(id: string): string {
  return `${window.location.origin}/?share=${encodeURIComponent(id)}&src=share`;
}

function clip(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= TEXT_MAX) return flat;
  const cut = flat.slice(0, TEXT_MAX - 1);
  return `${cut.slice(0, cut.lastIndexOf(" ") > 40 ? cut.lastIndexOf(" ") : cut.length)}…`;
}

/** The platforms, as the links their own share buttons open. */
export function destinations(
  url: string,
  text: string,
): { id: string; label: string; href: string }[] {
  const u = encodeURIComponent(url);
  const said = encodeURIComponent(text);
  return [
    { id: "whatsapp", label: "WhatsApp", href: `https://wa.me/?text=${said}%20${u}` },
    { id: "x", label: "X", href: `https://x.com/intent/post?text=${said}&url=${u}` },
    {
      id: "linkedin",
      label: "LinkedIn",
      href: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
    },
    {
      id: "telegram",
      label: "Telegram",
      href: `https://t.me/share/url?url=${u}&text=${said}`,
    },
    {
      id: "facebook",
      label: "Facebook",
      href: `https://www.facebook.com/sharer/sharer.php?u=${u}`,
    },
    { id: "email", label: "Email", href: `mailto:?subject=${said}&body=${u}` },
  ];
}

export function ShareSheet({
  tid,
  links,
  onShared,
  onClose,
}: {
  /** The answer being shared. */
  tid: string;
  /** The links it already went out under (`Message.shares`). */
  links: ShareLink[];
  /** The links changed: the thread keeps them, as the server did. */
  onShared: (links: ShareLink[]) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [masked, setMasked] = useState(true);
  const [preview, setPreview] = useState<SharedAnswer | null>(null);
  const [made, setMade] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState(false);

  // The link this cut already has, if it has one: shown as made.
  const existing = links.find((link) => link.masked === masked)?.id ?? null;
  const link = made ?? existing;

  useEffect(() => {
    let live = true;
    setPreview(null);
    setMade(null);
    setFailed(false);
    shareTurn(tid, { masked, preview: true }).then(
      (cut) => live && setPreview(cut),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [tid, masked]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

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

  const create = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const share = await shareTurn(tid, { masked });
      setMade(share.id);
      onShared([
        ...links.filter((each) => each.masked !== masked),
        { id: share.id, masked },
      ]);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    const any = links[0]?.id ?? made;
    if (!any) return;
    setBusy(true);
    setFailed(false);
    try {
      await unshare(any);
      setMade(null);
      onShared([]);
      onClose();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const url = link ? shareUrl(link) : "";
  const text = preview?.question
    ? t("chat.share_said", { question: clip(preview.question) })
    : t("chat.share_text");
  const native = typeof navigator !== "undefined" && "share" in navigator;

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
        aria-label={t("chat.share_title")}
        tabIndex={-1}
      >
        <div className="ag-share-head">
          <h2 className="ag-share-title">{t("chat.share_title")}</h2>
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

        <label className="ag-share-mask">
          <input
            type="checkbox"
            checked={masked}
            disabled={busy}
            onChange={(event) => setMasked(event.target.checked)}
          />
          <span>
            {t("chat.share_mask")}
            <span className="ag-chat-hint">{t("chat.share_mask_help")}</span>
          </span>
        </label>

        <div className="ag-share-preview" aria-label={t("chat.share_preview")}>
          {preview ? (
            <SharedBody share={preview} onLeave={onClose} />
          ) : failed ? null : (
            <Status label={t("common.loading")} />
          )}
        </div>

        {failed && (
          <p className="ag-chat-hint" role="alert">
            {t("chat.share_failed")}
          </p>
        )}

        {link ? (
          <div className="ag-share-out">
            <div className="ag-share-link">
              <input
                className="ag-share-url"
                readOnly
                value={url}
                aria-label={t("chat.share_link")}
                onFocus={(event) => event.currentTarget.select()}
              />
              <button
                type="button"
                className="ag-btn"
                onClick={() => {
                  navigator.clipboard?.writeText(url).then(
                    () => setCopied(true),
                    () => {},
                  );
                }}
              >
                <Glyph name={copied ? "check" : "copy"} size={14} />
                {t(copied ? "chat.copied" : "chat.share_copy")}
              </button>
            </div>
            <span className="ag-sr" role="status">
              {copied ? t("chat.copied") : ""}
            </span>
            <div className="ag-share-to">
              {native && (
                <button
                  type="button"
                  className="ag-btn ag-btn-cta"
                  onClick={() => {
                    void navigator.share({ title: text, text, url }).catch(() => {});
                  }}
                >
                  <Glyph name="share" size={14} />
                  {t("chat.share_native")}
                </button>
              )}
              {destinations(url, text).map((to) => {
                const name = to.id === "email" ? t("chat.share_email") : to.label;
                return (
                  <a
                    key={to.id}
                    className="ag-btn ag-share-brand"
                    href={to.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={name}
                    aria-label={name}
                  >
                    <Glyph name={to.id} size={20} />
                  </a>
                );
              })}
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="ag-btn ag-btn-cta ag-share-make"
            disabled={busy || !preview}
            onClick={() => void create()}
          >
            {t("chat.share_create")}
          </button>
        )}

        {links.length > 0 || made ? (
          <button
            type="button"
            className="ag-chat-link ag-share-stop"
            disabled={busy}
            onClick={() => void stop()}
          >
            {t("chat.share_stop")}
          </button>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
