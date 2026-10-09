/**
 * The filter bar: what to include, one chip per sector in the read, and
 * weight bands — folded behind a "Filters" button.
 *
 * Three rows of chips (eleven sectors wrap to two on a desktop) sat between
 * the page's title and its map on every visit, for a control most visits never
 * touch. So the bar is one line: the button, with how many picks are on; while
 * folded, each pick as a removable pill, so a filtered read never hides that
 * it is filtered; and the "21 of 51 · Clear" count. The chips open under it.
 *
 * "Include" comes first because it decides what the other two cut: the book,
 * the watchlist's starred names, the whole watchlist or one of its groups,
 * multi-pick, "All" clears. It is only drawn when there is a choice to make —
 * a book with no watchlist has nothing to narrow to.
 *
 * Sectors are multi-pick (a reader comparing tech with semis wants both);
 * "All" clears them. A weight band is one pick, pressed again to clear, and is
 * only drawn when something is held — outside names have no weight. Counts sit
 * on the sector chips so a sector with one name is not a surprise.
 */

import { type ReactNode, useId, useState } from "react";
import { Icon } from "../../shell/Icon";
import { useT } from "../../shell/i18n";
import { Help } from "../../ui/Kpi";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";
import { maybe } from "../sentiment/format";
import {
  BAND_ORDER,
  CLEAR,
  type Filter,
  isFiltered,
  listName,
  sectorsOf,
  sourcesOf,
} from "./filter";
import type { Review } from "./types";

/** A bucket's words: Pulse's sector name, else Yahoo's own spelling. */
function useSectorName() {
  const t = useT();
  return (key: string, name = key) => maybe(t, `sentiment.sector_${key}`) ?? name;
}

/** A source's words: the catalog's for the fixed ones, a group's own name. */
function useSourceName() {
  const t = useT();
  return (key: string) => listName(key) ?? t(`review.include_${key}`);
}

/** The filter in words, for the question to the assistant; "" when off. */
export function useFilterWords(filter: Filter): string {
  const t = useT();
  const name = useSectorName();
  const source = useSourceName();
  const parts: string[] = [];
  if (filter.sources.length) parts.push(filter.sources.map(source).join(" + "));
  if (filter.sectors.length)
    parts.push(filter.sectors.map((key) => name(key)).join(", "));
  if (filter.band) {
    parts.push(`${t("review.filter_weight")} ${t(`review.weight_${filter.band}`)}`);
  }
  return parts.join(" · ");
}

export function Filters({
  data,
  shown,
  filter,
  onChange,
  aside,
}: {
  /** The whole read: the chips are what it holds, not what is left. */
  data: Review;
  shown: Review;
  filter: Filter;
  onChange: (next: Filter) => void;
  /** Drawn at the far end of the bar (the read's date). */
  aside?: ReactNode;
}) {
  const t = useT();
  const name = useSectorName();
  const source = useSourceName();
  const [open, setOpen] = useState(false);
  const panel = useId();
  const total = data.held.length + data.candidates.length;
  if (total < 2) return <div className="ag-rev-filterbar">{aside}</div>;
  const sources = sourcesOf(data);
  for (const key of filter.sources) {
    if (!sources.some((s) => s.key === key)) sources.push({ key, count: 0 });
  }
  const sectors = sectorsOf(data);
  // A sector picked in the URL that this read has none of still gets its
  // chip, so it can be switched off where it was switched on.
  for (const key of filter.sectors) {
    if (!sectors.some((sector) => sector.key === key)) {
      sectors.push({ key, name: key, count: 0 });
    }
  }
  const toggle = (picked: string[], key: string) =>
    picked.includes(key) ? picked.filter((k) => k !== key) : [...picked, key];
  const flip = (key: string) =>
    onChange({ ...filter, sectors: toggle(filter.sectors, key) });
  const sectorName = (key: string) =>
    name(key, sectors.find((sector) => sector.key === key)?.name);

  // Every pick on, in the order the rows draw them, each with its own undo.
  const picks = [
    ...filter.sources.map((key) => ({
      key: `in-${key}`,
      label: source(key),
      off: () => onChange({ ...filter, sources: toggle(filter.sources, key) }),
    })),
    ...filter.sectors.map((key) => ({
      key: `sector-${key}`,
      label: sectorName(key),
      off: () => flip(key),
    })),
    ...(filter.band
      ? [
          {
            key: "band",
            label: t(`review.weight_${filter.band}`),
            off: () => onChange({ ...filter, band: null }),
          },
        ]
      : []),
  ];

  return (
    <section className="ag-rev-filters">
      <div className="ag-rev-filterbar">
        <button
          type="button"
          className={`ag-toggle ag-rev-filter-btn${open ? " ag-toggle-on" : ""}`}
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen(!open)}
        >
          <Icon name="filter_list" size={16} />
          {t("review.filters")}
          {picks.length > 0 && (
            <span className="ag-rev-filter-badge">{picks.length}</span>
          )}
        </button>
        {!open &&
          picks.map((pick) => (
            <button
              key={pick.key}
              type="button"
              className="ag-toggle ag-toggle-on ag-rev-pick"
              aria-label={t("review.filter_remove", { name: pick.label })}
              onClick={pick.off}
            >
              {pick.label}
              <span aria-hidden="true">×</span>
            </button>
          ))}
        {isFiltered(filter) && (
          <p className="ag-rev-caption ag-rev-filter-count" aria-live="polite">
            {t("review.filter_shown", {
              shown: shown.held.length + shown.candidates.length,
              total,
            })}
            <button
              type="button"
              className="ag-rev-filter-clear"
              onClick={() => onChange(CLEAR)}
            >
              {t("review.filter_clear")}
            </button>
          </p>
        )}
        {aside}
      </div>
      <div id={panel} className="ag-rev-filter-grid" hidden={!open}>
        {sources.length > 1 && (
          <div className="ag-rev-filter">
            <span className="ag-rev-filter-label">
              {t("review.filter_include")}
              <Help text={t("review.filter_include_help")} />
            </span>
            <ToggleRow label={t("review.filter_include")}>
              <ToggleChip
                on={filter.sources.length === 0}
                onClick={() => onChange({ ...filter, sources: [] })}
              >
                {t("review.filter_all")}
              </ToggleChip>
              {sources.map((s) => (
                <ToggleChip
                  key={s.key}
                  on={filter.sources.includes(s.key)}
                  onClick={() =>
                    onChange({ ...filter, sources: toggle(filter.sources, s.key) })
                  }
                >
                  {source(s.key)}
                  <span className="ag-rev-filter-n">{s.count}</span>
                </ToggleChip>
              ))}
            </ToggleRow>
          </div>
        )}
        <div className="ag-rev-filter">
          <span className="ag-rev-filter-label">{t("review.filter_sector")}</span>
          <ToggleRow label={t("review.filter_sector")}>
            <ToggleChip
              on={filter.sectors.length === 0}
              onClick={() => onChange({ ...filter, sectors: [] })}
            >
              {t("review.filter_all")}
            </ToggleChip>
            {sectors.map((sector) => (
              <ToggleChip
                key={sector.key}
                on={filter.sectors.includes(sector.key)}
                onClick={() => flip(sector.key)}
              >
                {name(sector.key, sector.name)}
                <span className="ag-rev-filter-n">{sector.count}</span>
              </ToggleChip>
            ))}
          </ToggleRow>
        </div>
        {data.held.length > 0 && (
          <div className="ag-rev-filter">
            <span className="ag-rev-filter-label">
              {t("review.filter_weight")}
              <Help text={t("review.filter_weight_help")} />
            </span>
            <ToggleRow label={t("review.filter_weight")}>
              <ToggleChip
                on={filter.band === null}
                onClick={() => onChange({ ...filter, band: null })}
              >
                {t("review.filter_all")}
              </ToggleChip>
              {BAND_ORDER.map((band) => (
                <ToggleChip
                  key={band}
                  on={filter.band === band}
                  onClick={() =>
                    onChange({ ...filter, band: filter.band === band ? null : band })
                  }
                >
                  {t(`review.weight_${band}`)}
                </ToggleChip>
              ))}
            </ToggleRow>
          </div>
        )}
      </div>
    </section>
  );
}
