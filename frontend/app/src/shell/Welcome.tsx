/**
 * The first-login welcome: how the app works, in three lines.
 *
 * Three rows — an icon, a short line, a shorter caption — that say what
 * happens, in order: the statement goes in, the portfolio is worked out from
 * it, the assistant reads both. They are text, not doors. The list of things
 * to set up is Home's start card, and a second one here counted differently
 * and sent a newcomer to pages their book had not filled yet.
 *
 * Shown once per account, on the first load the card surface decides
 * (`Tour.firstLoad`), and stamped the moment it opens — a welcome seen twice
 * is no longer one. Home's start card carries on from here.
 *
 * Two ways on, both in the footer, and it takes neither by itself: the
 * import, which is the point, and the section guide first (`onTour`) for
 * someone who wants to see what they are importing into.
 */

import { useEffect, useRef } from "react";

import { Icon } from "./Icon";
import { useT } from "./i18n";
import { canonical } from "./pages";
import { useRoute } from "./router";
import { landing } from "./Tour";
import { useDialog } from "./useDialog";
import { useExitGhost } from "./useSheet";

type Target = {
  id: string;
  path: string | null;
  params: Record<string, string>;
  session: Record<string, string>;
};

/** Icon and the stem of the two catalog keys for each row. */
const ROWS = [
  // Import first: it is what everything else on the app derives from.
  { icon: "upload_file", key: "import" },
  { icon: "pie_chart", key: "portfolio" },
  { icon: "auto_awesome", key: "ai" },
] as const;

export function Welcome({
  steps,
  onClose,
  onTour,
}: {
  steps: Target[];
  onClose: () => void;
  /** "Look round": the section guide, from its first stop. */
  onTour: () => void;
}) {
  const t = useT();
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  useDialog(card);
  const { go } = useRoute();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Where the import lives, from the registry: a deploy without the step
  // draws no button rather than one that goes nowhere.
  const target = steps.find((s) => s.id === "import");
  const importNow =
    target && target.path !== null
      ? () => {
          onClose();
          go(canonical(target.path ?? ""), landing(target));
        }
      : null;

  return (
    <div ref={scrim} className="ag-tour-scrim" role="presentation" onClick={onClose}>
      <div
        ref={card}
        tabIndex={-1}
        className="ag-tour ag-welcome"
        role="dialog"
        aria-modal="true"
        aria-label={t("tour.hello_title")}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ag-tour-head">
          <span className="ag-tour-title">{t("tour.hello_title")}</span>
        </header>
        <h2 className="ag-tour-h">{t("tour.hello_heading")}</h2>
        <ol className="ag-welcome-steps">
          {ROWS.map((row, i) => (
            <li key={row.key} className="ag-welcome-row">
              <span className="ag-welcome-dot" aria-hidden="true">
                <Icon name={row.icon} size={20} />
              </span>
              <span className="ag-welcome-text">
                <span className="ag-welcome-line">
                  <span className="ag-welcome-n">{i + 1}</span>
                  {t(`tour.hello_${row.key}`)}
                </span>
                <span className="ag-welcome-cap">{t(`tour.hello_${row.key}_cap`)}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="ag-welcome-hint">{t("tour.hello_hint")}</p>
        <footer className="ag-tour-foot">
          <button type="button" className="ag-tour-quiet" onClick={onTour}>
            {t("tour.hello_later")}
          </button>
          {importNow ? (
            <button type="button" className="ag-tour-cta" onClick={importNow}>
              {t("tour.hello_cta")}
            </button>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
