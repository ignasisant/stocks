/**
 * Where a made link goes: the link itself with a copy button, the device's
 * own share sheet where there is one, and the main platforms as plain links
 * everywhere — the desktop sheet is thin, and a link to wa.me is one every
 * browser can follow.
 */

import { useEffect, useState } from "react";
import { Glyph } from "../chat/icons";
import { useT } from "../shell/i18n";
import { destinations } from "./link";
import "./share.css";

export function ShareOut({
  url,
  text,
  label,
}: {
  url: string;
  text: string;
  label?: string;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const native = typeof navigator !== "undefined" && "share" in navigator;

  return (
    <div className="ag-share-out">
      <div className="ag-share-link">
        <input
          className="ag-share-url"
          readOnly
          value={url}
          aria-label={label ?? t("chat.share_link")}
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
  );
}
