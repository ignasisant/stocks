/**
 * The box that weighs names nobody follows yet.
 *
 * The top bar's search, as a picker: a chosen row (or a symbol nothing
 * matched, on Enter) goes into `?add=` and nowhere else: the list is a link, it
 * survives a reload, and it is gone once the reader removes it. Checked here
 * against the shape the server accepts, so a typo reads as a note under the
 * box instead of a failed page.
 */

import { useState } from "react";
import { Search } from "../../shell/Search";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { MAX_ADDED, SYMBOL } from "./format";

export function AddTickers({
  added,
  onChange,
}: {
  added: string[];
  onChange: (next: string[]) => void;
}) {
  const t = useT();
  const [note, setNote] = useState<string | null>(null);

  const pick = (ticker: string) => {
    const symbol = ticker.trim().toUpperCase();
    if (!SYMBOL.test(symbol)) {
      setNote(t("review.add_bad", { ticker: symbol }));
      return;
    }
    if (added.includes(symbol)) {
      setNote(null);
      return;
    }
    if (added.length >= MAX_ADDED) {
      setNote(t("review.add_max", { max: MAX_ADDED }));
      return;
    }
    setNote(null);
    onChange([...added, symbol]);
  };

  return (
    <div className="ag-rev-add">
      <p className="ag-rev-add-label">{t("review.add_label")}</p>
      <Search onPick={pick} placeholder={t("review.add_placeholder")} />
      {note ? (
        <p className="ag-rev-caption ag-rev-add-note" role="status">
          {note}
        </p>
      ) : null}
      {added.length > 0 ? (
        <ul className="ag-rev-added" aria-label={t("review.added_label")}>
          {added.map((symbol) => (
            <li key={symbol}>
              <TickerCell ticker={symbol} name={false} />
              <button
                type="button"
                aria-label={t("review.remove", { ticker: symbol })}
                onClick={() => onChange(added.filter((other) => other !== symbol))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
