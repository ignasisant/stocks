/**
 * The written read under the podium.
 *
 * Streamlit's card, over `GET`/`POST /sectors/{sector}/verdict`. The GET never
 * spends and answers with the stored read or the computed stand-in; the POST
 * has one written. For a signed-in reader the page asks for it on arrival,
 * exactly as the Streamlit card starts its generation when the page draws — a
 * read that has to be requested with a button is a read nobody requests — and
 * the server keys the stored one by tonight's scan, so arriving twice the same
 * night spends once.
 *
 * Its own card, like the podium above it. Without one the read sits loose
 * between the podium and the table and parses as page copy, which is the wrong
 * claim for the one block on this page a model wrote.
 */

import { useEffect, useState } from "react";
import { get, send } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { useGuest } from "../../shell/session";
import { Skeleton } from "../../shell/Layout";

type Read = {
  sector: string;
  as_of: string;
  lang: string;
  headline: string;
  bullets: string[];
  written: boolean;
};

export function Verdict({ sector }: { sector: string }) {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const [read, setRead] = useState<Read | null>(null);
  const [writing, setWriting] = useState(false);

  useEffect(() => {
    let alive = true;
    const at = `/sectors/${encodeURIComponent(sector)}/verdict`;
    setRead(null);
    (async () => {
      try {
        const stored = await get<Read>(at, { lang });
        if (!alive) return;
        // A guest can store nothing and may spend nothing: the stand-in is
        // their answer, as it is on the Streamlit card.
        if (stored.written || guest) {
          setRead(stored);
          return;
        }
        setWriting(true);
        const written = await send<Read>(
          "POST",
          `${at}?lang=${encodeURIComponent(lang)}`,
        ).catch(() => stored);
        if (alive) setRead(written);
      } catch {
        if (alive) setRead(null);
      } finally {
        if (alive) setWriting(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [sector, lang, guest]);

  if (!read && !writing) return null;
  return (
    <section className="ag-sec-card ag-sec-verdict">
      <h2 className="ag-sec-h2">{t("sector.verdict_title")}</h2>
      {writing || !read ? (
        <>
          <Skeleton rows={3} />
          <p className="ag-sec-caption">{t("sector.verdict_waiting")}</p>
        </>
      ) : (
        <>
          <p className="ag-sec-verdict-head">{read.headline}</p>
          {read.bullets.map((line, i) => (
            <p key={i} className="ag-sec-verdict-line">
              {line}
            </p>
          ))}
          {/* Said plainly when nothing was written: a stand-in that looked like
              the assistant's read would be the wrong claim twice over. */}
          {!read.written && (
            <p className="ag-sec-verdict-note">
              {t(guest ? "sector.verdict_signin" : "sector.verdict_computed")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
