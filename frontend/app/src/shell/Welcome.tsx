/**
 * The first-login welcome: three steps to a live portfolio, in a few words.
 *
 * What the "New here?" card on Home used to say in a paragraph, said as three
 * rows — an icon, a short line, a shorter caption — each one a door into the
 * section that does it. The sections teach themselves (Import has its own
 * stepper), so the pop-up does not explain them: it gets the reader there.
 *
 * Import leads: the ledger is what Portfolio, risk and taxes are built from.
 * Then the portfolio it fills, then the assistant that reads both.
 *
 * Shown once per account, on the first load the card surface decides
 * (`Tour.firstLoad`), and stamped the moment it opens — a welcome seen twice
 * is no longer one. Home's start card carries on from here.
 */

import { useEffect } from "react";

import { openAssistant } from "./assistant";
import { Icon } from "./Icon";
import { useT } from "./i18n";
import { canonical } from "./pages";
import { useRoute } from "./router";
import { landing } from "./Tour";

type Target = {
  id: string;
  path: string | null;
  params: Record<string, string>;
  session: Record<string, string>;
};

/** Registry step id, icon, and the two catalog keys for its row. */
const ROWS = [
  // Import first: it is the step everything else on the app derives from.
  { step: "import", icon: "upload_file", key: "import" },
  { step: "positions", icon: "pie_chart", key: "portfolio" },
  { step: "assistant", icon: "auto_awesome", key: "ai" },
] as const;

export function Welcome({ steps, onClose }: { steps: Target[]; onClose: () => void }) {
  const t = useT();
  const { go } = useRoute();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The step a row lands on, from the registry: a deploy without it draws
  // the row as text rather than as a button that goes nowhere.
  const visit = (id: string) => {
    const step = steps.find((s) => s.id === id);
    if (!step) return null;
    if (step.path === null) {
      // The assistant is a drawer, not a page: the registry says so with a
      // null path and asks for the panel open instead.
      if (!step.session?.chat_panel_open) return null;
      return () => {
        onClose();
        openAssistant();
      };
    }
    return () => {
      onClose();
      go(canonical(step.path ?? ""), landing(step));
    };
  };
  const importNow = visit("import");

  return (
    <div className="ag-tour-scrim" role="presentation" onClick={onClose}>
      <div
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
          {ROWS.map((row, i) => {
            const onClick = visit(row.step);
            const body = (
              <>
                <span className="ag-welcome-dot" aria-hidden="true">
                  <Icon name={row.icon} size={20} />
                </span>
                <span className="ag-welcome-text">
                  <span className="ag-welcome-line">
                    <span className="ag-welcome-n">{i + 1}</span>
                    {t(`tour.hello_${row.key}`)}
                  </span>
                  <span className="ag-welcome-cap">
                    {t(`tour.hello_${row.key}_cap`)}
                  </span>
                </span>
              </>
            );
            return (
              <li key={row.step}>
                {onClick ? (
                  <button type="button" className="ag-welcome-row" onClick={onClick}>
                    {body}
                    <span className="ag-welcome-go" aria-hidden="true">
                      <Icon name="arrow_forward" size={16} />
                    </span>
                  </button>
                ) : (
                  <span className="ag-welcome-row">{body}</span>
                )}
              </li>
            );
          })}
        </ol>
        <p className="ag-welcome-hint">{t("tour.hello_hint")}</p>
        <footer className="ag-tour-foot">
          {importNow ? (
            <button type="button" className="ag-tour-cta" onClick={importNow}>
              {t("tour.hello_cta")}
            </button>
          ) : null}
          <button type="button" className="ag-tour-quiet" onClick={onClose}>
            {t("tour.hello_later")}
          </button>
        </footer>
      </div>
    </div>
  );
}
