/**
 * The book's own history: what was put in against what it is worth.
 *
 * Sits under the positions table, where the Streamlit page puts it, and asks
 * the server for the window rather than slicing a long series locally. That is
 * not laziness — the y-axis has to rescale to what is on screen, and the TWR
 * index the same endpoint carries is rebased to the requested window, so a
 * client that fetched everything and sliced it would draw a one-month chart
 * starting at last year's cumulative return.
 */

import { useState } from "react";

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import type { History as HistoryData } from "./api";
import { BookHistory } from "./charts";
import { moneyIn, percent } from "./format";
import { Caption, Card, Segmented } from "./ui";

// The same codes the Streamlit range control offers and the API accepts, so a
// page and a client open on two screens draw the same span. Only "all" is
// translated: the rest are read as durations in every language this ships in.
const WINDOWS = ["1m", "3m", "6m", "1y", "ytd", "all"] as const;
type Window = (typeof WINDOWS)[number];

export default function History() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const [window, setWindow] = useState<Window>("all");

  const query = useApi(
    () => get<HistoryData>("/portfolio/history", { base, window }),
    [base, window],
  );

  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) => date.format(new Date(`${iso}T00:00:00`));

  return (
    <Card title={t("portfolio.injected_vs_value")}>
      <Segmented
        label={t("portfolio.range")}
        options={WINDOWS}
        value={window}
        onChange={setWindow}
        format={(option) =>
          option === "all" ? t("portfolio.range_all") : option.toUpperCase()
        }
      />
      <Loaded query={query} skeleton={<Skeleton rows={6} />}>
        {(history) =>
          history.points.length < 2 ? (
            <Caption>{t("portfolio.not_enough_history")}</Caption>
          ) : (
            <>
              <BookHistory
                points={history.points}
                labels={{
                  injected: t("portfolio.series_injected"),
                  profit: t("portfolio.series_value_profit"),
                  loss: t("portfolio.series_value_loss"),
                  pnl: t("portfolio.hist_pnl"),
                  reset: t("portfolio.zoom_reset"),
                }}
                money={(value, signed) => money(value, { signed }) ?? ""}
                percent={(value) => percent(lang, value, { signed: true }) ?? ""}
                formatDate={formatDate}
              />
              <Caption>
                {t("portfolio.hist_note_injected")} {t("portfolio.zoom_hint")}
                {history.missing.length
                  ? ` ${t("portfolio.hist_note_missing", {
                      tickers: history.missing.join(", "),
                    })}`
                  : ""}
              </Caption>
            </>
          )
        }
      </Loaded>
    </Card>
  );
}
