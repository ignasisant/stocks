/**
 * The flat view: what is coming, then what already printed.
 *
 * The phone default, and the reason the grid is not the only view — seven
 * columns at 390px squeeze a day cell to about 55px and the chips ellipsize to
 * nothing. Two plain tables say the same thing with the numbers left legible.
 */

import { useT } from "../../shell/i18n";
import type { CalendarEvent, CalendarResult } from "./data";
import { days, eps, longDate, plain, signedPct, tone } from "./format";
import { TickerCell } from "../../shell/tickers";

function Ticker({ ticker }: { ticker: string }) {
  return (
    <TickerCell className="earn-ticker" ticker={ticker}>
      {ticker}
    </TickerCell>
  );
}

function Upcoming({ events }: { events: CalendarEvent[] }) {
  const t = useT();
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.upcoming"))}</h2>
      <table className="earn-table">
        <thead>
          <tr>
            <th className="left">{t("earnings.list_col_ticker")}</th>
            <th className="left">{t("earnings.list_col_date")}</th>
            <th>{t("earnings.list_col_days_out")}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.ticker}>
              <td className="left">
                <Ticker ticker={event.ticker} />
              </td>
              <td className="left">
                {event.date === null ? "" : longDate(event.date, t)}
              </td>
              <td>{days(event.days_until)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Past({ results }: { results: CalendarResult[] }) {
  const t = useT();
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.past_results"))}</h2>
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
    </section>
  );
}

export default function ResultList({
  events,
  results,
}: {
  events: CalendarEvent[];
  results: CalendarResult[];
}) {
  return (
    <>
      {events.length > 0 && <Upcoming events={events} />}
      {results.length > 0 && <Past results={results} />}
    </>
  );
}
