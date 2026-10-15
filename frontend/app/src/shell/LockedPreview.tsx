/**
 * A page drawn behind glass, with the one step that opens it on top.
 *
 * For a screen that only means something once the reader has done a thing
 * first — Review judges a book, and an account with no import has none. A
 * blank card would say "nothing here"; the page itself, filled from the demo
 * book and blurred, says what is waiting, and the card says how to get it.
 *
 * What is behind is `inert` and hidden from assistive tech: it is a picture
 * of the page, not part of it, and a tab stop into a blurred table would be a
 * trap. The card is the page's only content as far as a screen reader knows.
 */

import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { Link } from "./router";

export function LockedPreview({
  title,
  body,
  cta,
  aside,
  children,
}: {
  title: string;
  body: string;
  /** The step that opens the page: one, and a page in the app. */
  cta: { label: string; page: string; params?: Record<string, string> };
  /** A quieter second way in, under the button. */
  aside?: ReactNode;
  /** The page as it would be, from data that is not the reader's. */
  children: ReactNode;
}) {
  return (
    <div className="ag-locked">
      <div className="ag-locked-behind" inert aria-hidden="true">
        {children}
      </div>
      <section className="ag-locked-card" aria-labelledby="ag-locked-title">
        <Icon name="lock" size={22} />
        <h2 id="ag-locked-title" className="ag-locked-title">
          {title}
        </h2>
        <p className="ag-locked-body">{body}</p>
        <Link className="ag-locked-go" page={cta.page} params={cta.params}>
          {cta.label}
          <Icon name="arrow_forward" size={18} />
        </Link>
        {aside ? <div className="ag-locked-aside">{aside}</div> : null}
      </section>
    </div>
  );
}
