/**
 * One of the "other ways" in under the drop zone: a tile with what it does,
 * when to reach for it, and where it goes.
 *
 * The trailing glyph is the destination, so two tiles that look alike still
 * say they behave differently before they are pressed: a chevron opens
 * something here, the side-panel mark hands off to the chat drawer.
 */

import type { ButtonHTMLAttributes } from "react";
import { Glyph, type GlyphName } from "./Glyph";

export function Way({
  icon,
  title,
  sub,
  trail,
  accent = false,
  ...button
}: {
  icon: GlyphName;
  title: string;
  sub: string;
  trail: GlyphName;
  /** The assistant's tile: its icon on the brand tint. */
  accent?: boolean;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "title" | "type">) {
  return (
    <button
      className={accent ? "im-way im-way-accent" : "im-way"}
      type="button"
      {...button}
    >
      <span aria-hidden="true" className="im-way-icon">
        <Glyph name={icon} />
      </span>
      <span className="im-way-text">
        <span className="im-way-title">{title}</span>
        <span className="im-way-sub">{sub}</span>
      </span>
      <span aria-hidden="true" className="im-way-trail">
        <Glyph name={trail} />
      </span>
    </button>
  );
}
