/**
 * The flat view: what is coming, week by week (`Agenda`), then the dividends
 * that already went ex and what already printed.
 *
 * The phone default, and the reason the grid is not the only view — seven
 * columns at 390px squeeze a day cell to about 55px and the chips ellipsize to
 * nothing. Two plain tables say the same thing with the numbers left legible.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import Agenda from "./Agenda";
import type {
  CalendarDividend,
  CalendarEvent,
  CalendarResult,
  CentralBankDecision,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { DividendTable } from "./Dividends";
import { eps, longDate, plain, signedPct, tone } from "./format";
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { DenseRows, Responsive } from "../../ui/Rows";

/**
 * Logo, symbol and — under it — the company's name. The name rides the same
 * batched profile lookup the logo does, so it costs nothing extra, and it is
 * simply absent while no catalog knows it rather than a placeholder.
 */
function Ticker({ ticker }: { ticker: string }) {
  const profile = useTickerProfile(ticker);
  return (
    <>
      <TickerCell className="earn-ticker" ticker={ticker}>
        {ticker}
      </TickerCell>
      {profile?.name && <div className="earn-name">{profile.name}</div>}
    </>
  );
}

/** Past prints shown before "show more": the latest are the ones worth a look. */
const PAST_ROWS = 8;

function Past({ all }: { all: CalendarResult[] }) {
  const t = useT();
  const [cap, setCap] = useState(PAST_ROWS);
  const results = all.slice(0, cap);
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.past_results"))}</h2>
      <Responsive
        wide={
          <table className="earn-table">
            <thead>
              <tr>
                <th className="left">{t("earnings.list_col_ticker")}</th>
                <th className="left">{t("earnings.list_col_date")}</th>
                <th>{t("earnings.list_col_eps_est")}</th>
                <th>{t("earnings.list_col_reported")}</th>
                <th>{t("earnings.list_col_surprise")}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr key={`${result.ticker}-${result.date}`}>
                  <td className="left">
                    <Ticker ticker={result.ticker} />
                  </td>
                  <td className="left">{longDate(result.date, t)}</td>
                  <td>{eps(result.eps_estimate)}</td>
                  <td>{eps(result.reported_eps)}</td>
                  {/* Coloured by the surprise itself, not by `beat`: a result with
                  nothing to compare has no colour to be given. */}
                  <td className={tone(result.surprise_pct)}>
                    {signedPct(result.surprise_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        }
        narrow={
          <DenseRows
            rows={results}
            rowKey={(result) => `${result.ticker}-${result.date}`}
            spec={{
              ticker: (result) => result.ticker,
              value: (result) => eps(result.reported_eps),
              delta: (result) => (
                <span className={tone(result.surprise_pct)}>
                  {signedPct(result.surprise_pct)}
                </span>
              ),
              sub: (result) => [
                longDate(result.date, t),
                `${t("earnings.list_col_eps_est")} ${eps(result.eps_estimate)}`,
              ],
            }}
          />
        }
      />
      {all.length > cap && (
        <button
          type="button"
          className="ag-btn earn-show-more"
          onClick={() => setCap(cap + PAST_ROWS)}
        >
          {t("earnings.show_more_results")}
        </button>
      )}
    </section>
  );
}

export default function ResultList({
  events,
  results,
  deadlines,
  windows,
  banks,
  dividends,
}: {
  events: CalendarEvent[];
  results: CalendarResult[];
  deadlines: TaxDeadline[];
  windows: RepurchaseWindow[];
  banks: CentralBankDecision[];
  dividends: CalendarDividend[];
}) {
  return (
    <>
      <Agenda
        events={events}
        deadlines={deadlines}
        windows={windows}
        banks={banks}
        dividends={dividends}
      />
      <DividendTable dividends={dividends.filter((d) => d.days_until < 0)} />
      {results.length > 0 && <Past all={results} />}
    </>
  );
}
