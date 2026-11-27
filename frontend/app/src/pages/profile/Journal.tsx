/**
 * Perfil → Diario: the reader's rules by holding (`JournalRules`), then the
 * decision journal whole, filtered in place.
 *
 * One read of `GET /journal` and the filters work on what came back: the
 * journal is capped at a few hundred entries, and a filter that answers
 * between keystrokes beats one that waits on a round trip each time.
 * Proposals and rules are listed apart, and the state chips count what each
 * would show under the other filters — "Keep" included only when it is
 * shown — so a reader sees "Abierta · 3" before pressing it and gets three.
 */

import { useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { Link } from "../../shell/router";
import { useAssistantChanges } from "../../shell/assistant";
import { useApi } from "../../shell/useApi";
import {
  type JournalEntry,
  type JournalRecord,
  type JournalSource,
  type JournalState,
  JournalList,
  SOURCES,
  STATES,
  getJournal,
} from "../../ui/Journal";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { JournalRules } from "./JournalRules";
import { Card, Chips, Inline, Row, Select } from "./ui";

type StateFilter = "all" | JournalState;
type SourceFilter = "all" | JournalSource;
type KindFilter = "proposals" | "rules";

/** The symbol without its exchange suffix, the way a reader types it. */
function bare(ticker: string): string {
  return ticker.split(".")[0]?.toLowerCase() ?? "";
}

export function Journal() {
  const t = useT();
  const saved = useAssistantChanges("set_criteria");
  const query = useApi(() => getJournal(), [saved]);
  return (
    <Card title={t("journal.title")}>
      <JournalRules saved={saved} />
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
            <>
              <div className="pr-cardbody jc-lede">
                <h3 className="pr-subhead">{t("journal.log_title")}</h3>
                <p className="pr-hint">{t("journal.log_intro")}</p>
              </div>
              <Record record={journal.record} />
              <Filtered entries={journal.entries} />
              {/* The same file a notes app reads whole: block ids, links
                  between entries, tags per ticker, state and source. */}
              <Row label={t("journal.export")} help={t("journal.export_help")}>
                <a className="pr-download" href="/api/v1/journal.md">
                  {t("journal.export_button")}
                </a>
              </Row>
            </>
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

/**
 * One line on what the reader did with the advice: how many moves were
 * proposed and how many they took, turned down, let lapse or still have
 * open. Counts, not a verdict on whether taking them paid.
 */
function Record({ record }: { record: JournalRecord }) {
  const t = useT();
  if (!record.proposed) return null;
  const tiles: [string, number][] = [
    ["journal.kpi_proposed", record.proposed],
    ["journal.kpi_followed", record.followed],
    ["journal.kpi_declined", record.declined],
    ["journal.kpi_lapsed", record.lapsed],
    ["journal.kpi_open", record.open],
  ];
  return (
    <div className="pr-cardbody">
      <KpiGrid>
        {tiles.map(([key, n]) => (
          <Kpi key={key} label={t(key)} value={String(n)} />
        ))}
        {record.marked ? (
          <Kpi
            label={t("journal.kpi_its_way")}
            value={`${record.its_way ?? 0}/${record.marked}`}
          />
        ) : null}
      </KpiGrid>
      {/* Counts, not a verdict on whether taking them paid. */}
      <p className="pr-hint">
        <Inline text={t("journal.record_note")} />
      </p>
    </div>
  );
}

function Filtered({ entries }: { entries: JournalEntry[] }) {
  const t = useT();
  const [state, setState] = useState<StateFilter>("all");
  const [source, setSource] = useState<SourceFilter>("all");
  const [ticker, setTicker] = useState("");
  // "Keep the book as it is" asks for nothing, so it is out of the list until
  // asked for; its count stays on the toggle.
  const [quiet, setQuiet] = useState(false);

  const filtered = useMemo(() => {
    const wanted = bare(ticker.trim());
    return entries.filter(
      (entry) =>
        (source === "all" || entry.source === source) &&
        (!wanted || bare(entry.ticker).startsWith(wanted)),
    );
  }, [entries, source, ticker]);
  const stays = filtered.filter((entry) => entry.action === "stay").length;
  const listed = quiet ? filtered : filtered.filter((entry) => entry.action !== "stay");
  // The reader's own rules sit apart from the proposals the app made, and
  // each list counts its own states.
  const ruleCount = listed.filter((entry) => entry.type === "criterion").length;
  const [kind, setKind] = useState<KindFilter>("proposals");
  const scope = listed.filter(
    (entry) => (entry.type === "criterion") === (kind === "rules"),
  );

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const entry of scope) out[entry.state] = (out[entry.state] ?? 0) + 1;
    return out;
  }, [scope]);

  const shown =
    state === "all" ? scope : scope.filter((entry) => entry.state === state);
  // A state no entry of this kind can be in is not offered.
  const stateOptions: StateFilter[] = [
    "all",
    ...STATES.filter((option) => counts[option] || option === state),
  ];
  const sourceOptions: SourceFilter[] = ["all", ...SOURCES];

  return (
    <>
      <Row label={t("journal.filter_kind")}>
        <Chips
          value={kind}
          options={["proposals", "rules"] as KindFilter[]}
          labelOf={(option) =>
            option === "rules"
              ? t("journal.rules_head", { n: ruleCount })
              : t("journal.proposals_head", { n: listed.length - ruleCount })
          }
          onPick={(option) => {
            setKind(option);
            setState("all");
          }}
        />
      </Row>
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
          autoComplete="off"
          autoCorrect="off"
          enterKeyHint="search"
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
        {stays > 0 && kind === "proposals" && (
          <label className="pr-check">
            <input
              type="checkbox"
              checked={quiet}
              onChange={(event) => setQuiet(event.target.checked)}
            />
            {t("journal.show_stay", { n: stays })}
          </label>
        )}
        {shown.length ? <JournalList entries={shown} /> : null}
      </div>
    </>
  );
}
