/**
 * Two blocks that are not about a price: what a coin is, and where the numbers
 * on this page come from.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { DASH, compactMoney, money, orElse } from "./format";
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
    // `compact_money`, as Streamlit prints them: "€1.5T", "€40.7B" — the mark
    // of the quote currency, one decimal. Supply is a count of coins, so it
    // takes the same rounding with no mark at all.
    [t("ticker.market_cap"), cell(compactMoney(stats.market_cap, stats.quote))],
    [t("ticker.volume_24h"), cell(compactMoney(stats.volume_24h, stats.quote))],
    [
      t("ticker.circulating_supply"),
      cell(compactMoney(stats.circulating_supply, null)),
    ],
    [
      t("ticker.range_52w"),
      // Half a range is not a range: one end missing leaves nothing to read
      // between, so the row says "n/a" rather than printing a lone bound.
      // Full precision, as Streamlit prints it ("16,212 – 98,050"): the range
      // of a coin is read against today's price, and "16.2K – 98.1K" loses the
      // very digits that comparison needs.
      stats.low_52w && stats.high_52w
        ? `${money(stats.low_52w, 0)} – ${money(stats.high_52w, 0)}`
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
                        <th>{t("kpi.col_note")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.kpis.map((row) => (
                        <tr key={row.key}>
                          {/* The catalog's name for the KPI, as Streamlit's
                              `kpi_label` reads it; the API's English string is
                              the fallback for a KPI nobody has translated. */}
                          <td title={orElse(t, `kpi.${row.key}.desc`, row.desc)}>
                            {orElse(t, `kpi.${row.key}.label`, row.label)}
                          </td>
                          <td>
                            {/* Provenance, muted but never absent: a consensus
                                figure shown bare wears a filing's authority. */}
                            <Tag tone={row.level === "consensus" ? "orange" : "gray"}>
                              {orElse(t, `kpi.level.${row.level}`, row.level)}
                            </Tag>
                          </td>
                          <td className="tk-muted">{row.loader}</td>
                          <td className="tk-muted">{row.verify}</td>
                          <td className="tk-muted">
                            {row.note ? orElse(t, `kpi.${row.key}.note`, row.note) : ""}
                          </td>
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
