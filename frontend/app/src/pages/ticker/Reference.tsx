/**
 * Two blocks that are not about a price: what a coin is, and where the numbers
 * on this page come from.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded } from "../../shell/Layout";
import { Responsive, StackCards } from "../../ui/Rows";
import { useT } from "../../shell/i18n";
import { DASH, compactMoney, money, orElse, percent, type Translate } from "./format";
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
    // `stocks.formatting.compact_money`'s shape: "€1.5T", "€40.7B" — the mark
    // of the quote currency, one decimal. Supply is a count of coins, so it
    // takes the same rounding with no mark at all.
    [t("ticker.market_cap"), cell(compactMoney(stats.market_cap, stats.quote))],
    [t("ticker.volume_24h"), cell(compactMoney(stats.volume_24h, stats.quote))],
    [
      t("ticker.circulating_supply"),
      cell(compactMoney(stats.circulating_supply, null)),
    ],
    // Tokenomics: how much of the supply is out, and what the rest is
    // already priced at. Rows the scan has no figure for are left out rather
    // than printed as "n/a" — an uncapped coin has no hard cap to report.
    ...(stats.max_supply
      ? ([
          [
            t("ticker.max_supply"),
            `${compactMoney(stats.max_supply, null)}${
              stats.issued_pct !== null && stats.issued_pct !== undefined
                ? ` · ${t("ticker.issued", { pct: percent(stats.issued_pct, 0) })}`
                : ""
            }`,
          ],
        ] as [string, string][])
      : []),
    ...(stats.fdv
      ? ([[t("ticker.fdv"), compactMoney(stats.fdv, stats.quote)]] as [
          string,
          string,
        ][])
      : []),
    [
      t("ticker.range_52w"),
      // Half a range is not a range: one end missing leaves nothing to read
      // between, so the row says "n/a" rather than printing a lone bound.
      // Full precision ("16,212 – 98,050"): the range of a coin is read against
      // today's price, and "16.2K – 98.1K" loses the very digits that
      // comparison needs.
      stats.low_52w && stats.high_52w
        ? `${money(stats.low_52w, 0)} – ${money(stats.high_52w, 0)}`
        : na,
    ],
  ];
  const ratio = stats.fdv_ratio ?? null;
  const head = [
    stats.rank ? t("ticker.rank", { n: stats.rank }) : "",
    categoryLabel(t, stats.category),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card title={t("ticker.asset_stats")} note={head || undefined}>
      <Metrics>
        {rows.map(([label, value]) => (
          <Metric key={label} label={label} value={value} />
        ))}
        {ratio !== null ? (
          <Metric
            label={t("ticker.fdv_ratio")}
            help={t("ticker.fdv_ratio_help")}
            value={`${ratio.toFixed(2)}×`}
            note={dilutionBand(t, stats.dilution)}
            // The server's band, coloured as `analysis.crypto_market` does.
            noteTone={stats.dilution === "heavy" ? "orange" : null}
          />
        ) : null}
      </Metrics>
      <Note>{t("ticker.crypto_caption", { quote: stats.quote })}</Note>
    </Card>
  );
}

/** What claim a coin is, in words. Literal keys, for the catalog scan. */
function categoryLabel(t: Translate, category: string | null | undefined): string {
  switch (category) {
    case "store_of_value":
      return t("ticker.crypto_cat_store_of_value");
    case "smart_contract":
      return t("ticker.crypto_cat_smart_contract");
    case "layer2":
      return t("ticker.crypto_cat_layer2");
    case "stablecoin":
      return t("ticker.crypto_cat_stablecoin");
    case "payments":
      return t("ticker.crypto_cat_payments");
    case "exchange":
      return t("ticker.crypto_cat_exchange");
    case "defi":
      return t("ticker.crypto_cat_defi");
    case "infrastructure":
      return t("ticker.crypto_cat_infrastructure");
    case "meme":
      return t("ticker.crypto_cat_meme");
    case "gaming":
      return t("ticker.crypto_cat_gaming");
    default:
      return "";
  }
}

function dilutionBand(t: Translate, band: string | null | undefined): string {
  switch (band) {
    case "none":
      return t("ticker.dilution_none");
    case "some":
      return t("ticker.dilution_some");
    case "heavy":
      return t("ticker.dilution_heavy");
    default:
      return "";
  }
}

/**
 * Where every KPI is loaded from and where to check it before acting on it.
 *
 * Collapsed, and fetched only when opened: it is reference data most readers
 * never expand, and it is the same table every time — so it hangs off `open`
 * rather than costing a request per company.
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
                <Responsive
                  wide={
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
                              {/* The catalog's name for the KPI; the API's
                              English string is the fallback for a KPI nobody
                              has translated. */}
                              <td title={orElse(t, `kpi.${row.key}.desc`, row.desc)}>
                                {orElse(t, `kpi.${row.key}.label`, row.label)}
                              </td>
                              <td>
                                {/* Provenance, muted but never absent: a consensus
                                figure shown bare wears a filing's authority. */}
                                <Tag
                                  tone={row.level === "consensus" ? "orange" : "gray"}
                                >
                                  {orElse(t, `kpi.level.${row.level}`, row.level)}
                                </Tag>
                              </td>
                              <td className="tk-muted">{row.loader}</td>
                              <td className="tk-muted">{row.verify}</td>
                              <td className="tk-muted">
                                {row.note
                                  ? orElse(t, `kpi.${row.key}.note`, row.note)
                                  : ""}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </Scroll>
                  }
                  narrow={
                    <StackCards
                      rows={data.kpis}
                      rowKey={(row) => row.key}
                      title={(row) => orElse(t, `kpi.${row.key}.label`, row.label)}
                      lines={[
                        {
                          label: t("kpi.col_level"),
                          cell: (row) => (
                            <Tag tone={row.level === "consensus" ? "orange" : "gray"}>
                              {orElse(t, `kpi.level.${row.level}`, row.level)}
                            </Tag>
                          ),
                        },
                        { label: t("kpi.col_loaded"), cell: (row) => row.loader },
                        { label: t("kpi.col_verify"), cell: (row) => row.verify },
                        {
                          label: t("kpi.col_note"),
                          cell: (row) =>
                            row.note ? orElse(t, `kpi.${row.key}.note`, row.note) : "",
                        },
                      ]}
                    />
                  }
                />
                <Note>{t("ticker.kpi_sources_caption", { n: data.kpis.length })}</Note>
              </>
            )
          }
        </Loaded>
      ) : null}
    </details>
  );
}
