/**
 * The earnings calendar: when the watchlist reports, and how it went last time.
 *
 * Aggressive growth names gap hard on prints, so this page leads with the
 * warning — how many reports land inside a week — and only then offers the two
 * views over the same data: a month grid, and a flat list.
 *
 * One request serves all of it. `/api/v1/earnings` returns the upcoming dates,
 * the past results, the filter groups and the names it deliberately left out,
 * because the single Yahoo pass that finds a next date already carries the past
 * quarters' columns.
 */

import "./earnings.css";
import { get } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { SignedInOnly, SignIn } from "../../shell/guest";
import { useApi } from "../../shell/useApi";
import type { EarningsCalendar } from "./data";
import { isSoon } from "./data";
import Views from "./Views";

/**
 * Nothing came back at all — no dates, no groups, not even a skipped name.
 *
 * That is an empty watchlist rather than a quiet quarter, so it gets the same
 * card the Streamlit page shows: what this screen is for, and the one place to
 * fix it. Anything else — names that report but have no published date yet —
 * falls through to `no_dates` below, which does not accuse the reader of having
 * added nothing.
 */
function NothingTracked() {
  const t = useT();
  return (
    <div className="earn-empty">
      <h2 className="earn-h2">{t("earnings.empty_title")}</h2>
      <p>{t("earnings.empty_body")}</p>
      {/* "Add tickers" is a link into Profile, which refuses a guest inside —
          so for a guest the one place to fix an empty watchlist is an account,
          and saying that is more use than sending them to a locked door. */}
      <SignedInOnly fallback={<SignIn />}>
        <Link className="ag-btn" page="profile">
          {t("common.cta_add_tickers")}
        </Link>
      </SignedInOnly>
    </div>
  );
}

function Body({ data }: { data: EarningsCalendar }) {
  const t = useT();
  const imminent = data.upcoming.filter(isSoon).length;
  const bare = data.upcoming.length === 0 && data.results.length === 0;
  const untracked =
    bare && Object.keys(data.groups).length === 0 && data.skipped.length === 0;
  return (
    <>
      {imminent > 0 && (
        <p className="earn-warn">{t("earnings.imminent_warning", { n: imminent })}</p>
      )}
      {bare ? (
        untracked ? (
          <NothingTracked />
        ) : (
          <p className="ag-note">{t("earnings.no_dates")}</p>
        )
      ) : (
        <Views data={data} />
      )}
      {/* The names that were dropped before the fetch, said out loud: a reader
          with their watchlist open beside this should not have to work out why
          a coin or a fund is missing from the calendar. */}
      {data.skipped.length > 0 && (
        <p className="earn-skipped">
          {t("earnings.skipped_note", { names: data.skipped.join(", ") })}
        </p>
      )}
    </>
  );
}

export default function Page() {
  const t = useT();
  const query = useApi(() => get<EarningsCalendar>("/earnings"), []);
  return (
    <>
      <h1 className="earn-title">{t("earnings.title")}</h1>
      <Loaded query={query} skeleton={<Skeleton rows={8} />}>
        {(data) => <Body data={data} />}
      </Loaded>
    </>
  );
}
