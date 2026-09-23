/**
 * Two blocks that are not about a price: what a coin is, and where the numbers
 * on this page come from.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { DASH, compact, orElse } from "./format";
import { Card, Metric, Metrics, Note, Scroll, Tag } from "./ui";
import type { AssetStats, KpiSourceRow } from "./types";

/**
 * The coin stand-in for fundamentals, insiders and comps — a currency pair has
 * none of those, and an empty page is not the same claim as "not applicable".
 */
export function AssetStatsSection({ stats }: { stats: AssetStats }) {
  const t = useT();
  const na = t("ticker.na");
  const cell = (value: string) => (value === DASH ? na : value);
  const rows: [string, string][] = [
    [t("ticker.market_cap"), cell(compact(stats.market_cap, stats.quote))],
    [t("ticker.volume_24h"), cell(compact(stats.volume_24h, stats.quote))],
    [t("ticker.circulating_supply"), cell(compact(stats.circulating_supply))],
    [
      t("ticker.range_52w"),
      // Half a range is not a range: one end missing leaves nothing to read
      // between, so the row says "n/a" rather than printing a lone bound.
      stats.low_52w !== null && stats.high_52w !== null
        ? `${compact(stats.low_52w)} – ${compact(stats.high_52w)}`
        : na,
    ],
  ];
  return (
    <Card title={t("ticker.asset_stats")}>
      <Metrics>
        {rows.map(([label, value]) => (
          <Metric key={label} label={label} value={value} />
        ))}
      </Metrics>
      <Note>{t("ticker.crypto_caption", { quote: stats.quote })}</Note>
    </Card>
  );
}

/**
 * Where every KPI is loaded from and where to check it before acting on it.
 *
 * Collapsed, as on the Streamlit page, and fetched only when opened: it is
 * reference data most readers never expand, and it is the same table every
 * time — so it hangs off `open` rather than costing a request per company.
 */
export function KpiSourcesSection() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const query = useApi(
    () =>
      open
        ? get<{ kpis: KpiSourceRow[] }>("/kpi-sources")
        : Promise.resolve<{ kpis: KpiSourceRow[] } | null>(null),
    [open],
  );

  return (
    <details
      className="tk-card tk-details"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{t("ticker.kpi_sources_title")}</summary>
      {open ? (
        <Loaded query={query}>
          {(data) =>
            !data || data.kpis.length === 0 ? null : (
              <>
                <Scroll>
                  <table className="tk-table">
                    <thead>
                      <tr>
                        <th>{t("kpi.col_kpi")}</th>
                        <th>{t("kpi.col_level")}</th>
                        <th>{t("kpi.col_loaded")}</th>
                        <th>{t("kpi.col_verify")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.kpis.map((row) => (
                        <tr key={row.key}>
                          <td title={row.desc}>{row.label}</td>
                          <td>
                            {/* Provenance, muted but never absent: a consensus
                                figure shown bare wears a filing's authority. */}
                            <Tag tone={row.level === "consensus" ? "orange" : "gray"}>
                              {orElse(t, `kpi.level.${row.level}`, row.level)}
                            </Tag>
                          </td>
                          <td className="tk-muted">{row.loader}</td>
                          <td className="tk-muted">{row.verify}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
                <Note>{t("ticker.kpi_sources_caption", { n: data.kpis.length })}</Note>
              </>
            )
          }
        </Loaded>
      ) : null}
    </details>
  );
}
