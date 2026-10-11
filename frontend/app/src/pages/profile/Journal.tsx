/**
 * Perfil → Diario: the decision journal whole, filtered in place.
 *
 * One read of `GET /journal` and the filters work on what came back: the
 * journal is capped at a few hundred entries, and a filter that answers
 * between keystrokes beats one that waits on a round trip each time. The
 * state chips count what each would show under the other filters, so a
 * reader sees "Abierta · 3" before pressing it.
 */

import { useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import {
  type JournalEntry,
  type JournalSource,
  type JournalState,
  JournalList,
  SOURCES,
  STATES,
  getJournal,
} from "../../ui/Journal";
import { Card, Chips, Inline, Row, Select } from "./ui";

type StateFilter = "all" | JournalState;
type SourceFilter = "all" | JournalSource;

/** The symbol without its exchange suffix, the way a reader types it. */
function bare(ticker: string): string {
  return ticker.split(".")[0]?.toLowerCase() ?? "";
}

export function Journal() {
  const t = useT();
  const query = useApi(() => getJournal(), []);
  return (
    <Card title={t("journal.title")}>
      <div className="pr-cardbody">
        <p className="pr-hint">
          <Inline text={t("journal.intro")} />
        </p>
      </div>
      <Loaded
        query={query}
        skeleton={
          <div className="pr-cardbody">
            <Skeleton rows={6} />
          </div>
        }
      >
        {(journal) =>
          journal.entries.length ? (
            <Filtered entries={journal.entries} />
          ) : (
            <div className="pr-cardbody">
              <p className="pr-hint">
                <Inline text={t("journal.empty")} />
              </p>
              {/* The one place proposals come from on demand. */}
              <Link page="review" className="pr-btn ag-jr-cta">
                {t("tour.review_cta")}
              </Link>
            </div>
          )
        }
      </Loaded>
    </Card>
  );
}

function Filtered({ entries }: { entries: JournalEntry[] }) {
  const t = useT();
  const [state, setState] = useState<StateFilter>("all");
  const [source, setSource] = useState<SourceFilter>("all");
  const [ticker, setTicker] = useState("");

  const scope = useMemo(() => {
    const wanted = bare(ticker.trim());
    return entries.filter(
      (entry) =>
        (source === "all" || entry.source === source) &&
        (!wanted || bare(entry.ticker).startsWith(wanted)),
    );
  }, [entries, source, ticker]);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const entry of scope) out[entry.state] = (out[entry.state] ?? 0) + 1;
    return out;
  }, [scope]);

  const shown =
    state === "all" ? scope : scope.filter((entry) => entry.state === state);
  const stateOptions: StateFilter[] = ["all", ...STATES];
  const sourceOptions: SourceFilter[] = ["all", ...SOURCES];

  return (
    <>
      <Row label={t("journal.filter_state")}>
        <Chips
          value={state}
          options={stateOptions}
          labelOf={(option) =>
            option === "all"
              ? `${t("journal.all_states")} · ${scope.length}`
              : `${t(`journal.state_${option}`)} · ${counts[option] ?? 0}`
          }
          onPick={setState}
        />
      </Row>
      <Row label={t("journal.filter_source")}>
        <Select
          value={source}
          options={sourceOptions}
          labelOf={(option) =>
            option === "all" ? t("journal.all_sources") : t(`journal.source_${option}`)
          }
          onPick={setSource}
          label={t("journal.filter_source")}
        />
      </Row>
      <Row label={t("journal.filter_ticker")}>
        <input
          className="pr-input pr-input-sm"
          type="search"
          value={ticker}
          placeholder={t("journal.filter_ticker_hint")}
          aria-label={t("journal.filter_ticker")}
          autoCapitalize="characters"
          spellCheck={false}
          onChange={(event) => setTicker(event.target.value)}
        />
      </Row>
      <div className="pr-cardbody">
        <p className="pr-hint" aria-live="polite">
          {shown.length
            ? t("journal.count", { n: shown.length })
            : t("journal.empty_filtered")}
        </p>
        {shown.length ? null : (
          <button
            type="button"
            className="pr-btn ag-jr-cta"
            onClick={() => {
              setState("all");
              setSource("all");
              setTicker("");
            }}
          >
            {t("journal.clear_filters")}
          </button>
        )}
        {shown.length ? <JournalList entries={shown} /> : null}
      </div>
    </>
  );
}
