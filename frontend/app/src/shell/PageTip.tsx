/**
 * A page's first-visit tip: how the page is used, in two or three lines, and
 * the lesson that teaches the idea behind it.
 *
 * Owed only to a newcomer. The server writes the list of pages that still owe
 * one on the account's first real import (`onboarding.first_book`), and it
 * rides the prefs the document already carries — so an account that has been
 * here before has an empty list, draws nothing and asks for nothing. The copy
 * is fetched only when a tip is actually drawn.
 *
 * "Got it" removes the page from that list, on the account rather than in the
 * browser: the tip is gone on every device, not only on this one. It waits
 * while the tour or the welcome is up, open or parked — two guides talking at
 * once is one too many — and it is not marked read for having waited.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { get, send } from "./api";
import { Icon } from "./Icon";
import { useLang, useT } from "./i18n";
import { Link, useRoute } from "./router";
import { useSession } from "./session";
import { isTouring, onTouring, readPark } from "./tourPark";

type Tip = {
  page: string;
  lines: number;
  lesson: { id: string; title: string; minutes: number } | null;
};

export function PageTip() {
  const { guest, prefs, reload } = useSession();
  const { page, params } = useRoute();
  const touring = useSyncExternalStore(onTouring, isTouring);
  // Read in this document before the write lands, so the tip does not come
  // back for the moment the session takes to refetch.
  const [seen, setSeen] = useState<string[]>([]);
  const owed = !guest && (prefs.page_tips ?? []).includes(page) && !seen.includes(page);
  // `?tour=` and a parked strip are read directly as well: the tour decides
  // once the browser is idle, and the tip must not flash up before it does.
  if (!owed || touring || params.has("tour") || readPark()) return null;
  return (
    <TipCard
      key={page}
      page={page}
      onSeen={() => {
        setSeen((pages) => [...pages, page]);
        // The button that had focus is gone; the page is where the reader
        // was headed, so focus goes to its column (`Layout`'s `MAIN_ID`).
        document.getElementById("ag-main")?.focus();
        void send("POST", `/onboarding/tips/${page}`, {}, { touches: ["/prefs"] })
          .then(reload)
          // Hidden for this visit either way; a failed write is one more
          // sight of the tip on the next load, not an error worth showing.
          .catch(() => undefined);
      }}
    />
  );
}

function TipCard({ page, onSeen }: { page: string; onSeen: () => void }) {
  const t = useT();
  const lang = useLang();
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    let alive = true;
    get<Tip>(`/onboarding/tips/${page}`, { lang })
      .then((body) => {
        if (alive) setTip(body);
      })
      // A tip that will not load is a tip nobody misses.
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [page, lang]);

  if (!tip) return null;
  const heading = `ag-visit-h-${page}`;
  return (
    <section className="ag-visit" aria-labelledby={heading}>
      <span className="ag-visit-eyebrow">{t("tour.tip_eyebrow")}</span>
      <h2 id={heading} className="ag-visit-h">
        {t("tour.tip_title", { page: t(`nav.${page}`) })}
      </h2>
      <ul className="ag-visit-lines">
        {Array.from({ length: tip.lines }, (_, i) => (
          <li key={i}>{t(`tour.tip_${page}_${i + 1}`)}</li>
        ))}
      </ul>
      <footer className="ag-visit-foot">
        {tip.lesson ? (
          <Link
            className="ag-visit-lesson"
            page="learn"
            params={{ lesson: tip.lesson.id }}
          >
            <Icon name="school" size={16} />
            <span>
              {t("tour.tip_lesson", { title: tip.lesson.title, n: tip.lesson.minutes })}
            </span>
          </Link>
        ) : null}
        <button type="button" className="ag-tour-cta ag-visit-ok" onClick={onSeen}>
          {t("tour.tip_ok")}
        </button>
      </footer>
    </section>
  );
}
