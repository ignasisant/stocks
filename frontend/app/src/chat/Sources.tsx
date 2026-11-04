/**
 * An answer's cited pages, folded under a count: the web pages it read and
 * the app pages it pointed at. Shared by a turn and a shared answer's view.
 */

import { useId, useState } from "react";
import { useT } from "../shell/i18n";
import { host } from "./format";
import { Glyph } from "./icons";
import { AppSource, type Source } from "./links";
import { href } from "./markdown";

export function Sources({ web, onLeave }: { web: Source[]; onLeave: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  // The list is drawn closed rather than left unmounted, so that the button's
  // `aria-controls` points at something that exists: an id that resolves to
  // nothing is the same as no id at all.
  const uid = useId();
  const listId = `${uid}-sources`;
  return (
    <>
      <button
        type="button"
        className="ag-chat-meta-btn"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
      >
        <Glyph name="link" size={12} />
        {t("chat.sources_n", { n: web.length })}
      </button>
      <ul className="ag-chat-sources" id={listId} hidden={!open}>
        {web.map((source, i) => (
          <li key={i}>
            {href(source.url) === null ? (
              <AppSource source={source} onLeave={onLeave} />
            ) : (
              <a
                className="ag-chat-a"
                href={href(source.url) ?? undefined}
                target="_blank"
                rel="noopener noreferrer nofollow"
                title={source.title}
              >
                {host(source.url)}
              </a>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
