/**
 * The overview a past chip opens: what the street expected, what printed.
 *
 * The Streamlit dialog goes further — revenue, margins, the GAAP result, EPS
 * quality and next quarter's consensus — but every one of those sections is
 * fetched per ticker, and `/api/v1` publishes no endpoint for them yet. Rather
 * than invent numbers or open a dialog that loads forever, this shows the three
 * figures the calendar payload already carries and hands the reader the ticker
 * page, which is where the rest of the quarter lives.
 */

import { useEffect } from "react";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import type { CalendarResult } from "./data";
import { eps, longDate, plain, signedNum, tone } from "./format";

export default function ResultDetail({
  result,
  onClose,
}: {
  result: CalendarResult;
  onClose: () => void;
}) {
  const t = useT();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const bare =
    result.reported_eps === null &&
    result.eps_estimate === null &&
    result.surprise_pct === null;

  return (
    <div
      className="earn-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="earn-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label={t("earnings.dialog_title")}
      >
        <div className="earn-modal-head">
          <div>
            <Link
              className="earn-ticker"
              page="ticker"
              params={{ ticker: result.ticker }}
            >
              {result.ticker}
            </Link>
            <div className="earn-modal-date">
              {plain(t("earnings.reported_on", { date: longDate(result.date, t) }))}
            </div>
          </div>
          <button type="button" className="earn-close" onClick={onClose}>
            {t("earnings.close")}
          </button>
        </div>

        {bare ? (
          <p className="ag-note">{t("earnings.no_figures")}</p>
        ) : (
          <div className="earn-tiles">
            <div className="earn-tile">
              <div className="earn-tile-label">{t("earnings.reported_eps")}</div>
              <div className="earn-tile-value">{eps(result.reported_eps)}</div>
              {result.surprise_pct !== null && (
                <div className={`earn-tile-delta ${tone(result.surprise_pct)}`}>
                  {t("earnings.surprise_vs_est", {
                    pct: signedNum(result.surprise_pct),
                  })}
                </div>
              )}
            </div>
            <div className="earn-tile">
              <div className="earn-tile-label">{t("earnings.eps_estimate")}</div>
              <div className="earn-tile-value">{eps(result.eps_estimate)}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
