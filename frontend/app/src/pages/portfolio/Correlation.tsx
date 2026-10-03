/**
 * The correlation card: what the grid says in four figures, how to read it,
 * and — on any cell — what that pair (or that one name) means for the book.
 *
 * A grid of forty names is a wall of red to anyone who has not read one
 * before. The figures on top answer the questions a reader brings to it (how
 * alike is my book, which two move as one, what diversifies it, where does
 * the risk come from, how much does it swing with the market); the caption
 * says what a colour means; the hover box turns a number into a sentence.
 */

import { useLang, useT } from "../../shell/i18n";
import type { Risk } from "./api";
import { correlationBand, correlationStats, Heatmap } from "./charts";
import { decimal, percent } from "./format";
import { Caption, Card, Kpis } from "./ui";

export function CorrelationCard({ data }: { data: Risk }) {
  const t = useT();
  const lang = useLang();
  const stats = correlationStats(data.correlation, data.weights);
  const num = (value: number) => decimal(lang, value) ?? "";
  const pct = (value: number | null | undefined) =>
    value == null ? "—" : (percent(lang, value, { digits: 1 }) ?? "—");
  const bench = Object.keys(data.betas)[0] ?? null;
  const book = bench ? data.betas[bench] : undefined;
  const band = (value: number) => t(`portfolio.corr_band_${correlationBand(value)}`);

  // The name carrying the most of the basket's swings.
  const riskiest = Object.entries(data.names)
    .filter(([, one]) => one.risk_share != null)
    .sort(([, a], [, b]) => b.risk_share! - a.risk_share!)[0];

  /** What one name's share of the risk says against its weight. */
  const riskStory = (name: string) => {
    const share = data.names[name]?.risk_share;
    const weight = data.weights[name];
    if (share == null || !weight) return null;
    if (share < 0) return t("portfolio.corr_risk_hedge");
    if (share > weight * 1.2) return t("portfolio.corr_risk_more");
    if (share < weight * 0.8) return t("portfolio.corr_risk_less");
    return t("portfolio.corr_risk_even");
  };

  const explain = (row: string, column: string) => {
    const value = data.correlation[row]?.[column];
    if (row === column) {
      const own = stats.perName[row];
      const story = riskStory(row);
      return (
        <>
          <span className="pf-tip-title">{row}</span>
          <span className="pf-heat-tip-story">
            {t("portfolio.corr_self_story", { a: row })}
            {story ? ` ${story}` : ""}
          </span>
          <Rows
            rows={[
              [t("portfolio.corr_tip_weight"), pct(data.weights[row])],
              [t("portfolio.corr_tip_vol"), pct(data.names[row]?.volatility)],
              ...(bench
                ? [
                    [
                      t("portfolio.corr_tip_beta", { bench }),
                      data.names[row]?.betas[bench] == null
                        ? "—"
                        : num(data.names[row]!.betas[bench]!),
                    ] as [string, string],
                  ]
                : []),
              [t("portfolio.corr_tip_risk"), pct(data.names[row]?.risk_share)],
              [
                t("portfolio.corr_tip_avg"),
                own?.average == null ? "—" : num(own.average),
              ],
              ...(own?.peer
                ? [
                    [
                      t("portfolio.corr_tip_peer"),
                      `${own.peer.name} · ${num(own.peer.value)}`,
                    ] as [string, string],
                  ]
                : []),
              ...(own?.hedge && own.hedge.name !== own.peer?.name
                ? [
                    [
                      t("portfolio.corr_tip_hedge"),
                      `${own.hedge.name} · ${num(own.hedge.value)}`,
                    ] as [string, string],
                  ]
                : []),
            ]}
          />
        </>
      );
    }
    const together = (data.weights[row] ?? 0) + (data.weights[column] ?? 0);
    return (
      <>
        <span className="pf-tip-title">
          {row} × {column}
        </span>
        {value === undefined ? (
          <span className="pf-heat-tip-story">{t("portfolio.corr_no_overlap")}</span>
        ) : (
          <>
            <span className="pf-heat-tip-value">
              {num(value)} · {band(value)}
            </span>
            <span className="pf-heat-tip-story">
              {t(`portfolio.corr_story_${correlationBand(value)}`, {
                a: row,
                b: column,
              })}
            </span>
          </>
        )}
        <Rows rows={[[t("portfolio.corr_tip_together"), pct(together)]]} />
        <span className="pf-heat-tip-names">
          <span className="pf-tip-head pf-heat-tip-who" />
          <span className="pf-tip-head">{t("portfolio.corr_tip_weight")}</span>
          <span className="pf-tip-head">{t("portfolio.corr_tip_vol")}</span>
          <span className="pf-tip-head">
            {bench ? t("portfolio.corr_tip_beta", { bench }) : "β"}
          </span>
          <span className="pf-tip-head">{t("portfolio.corr_tip_risk")}</span>
          {[row, column].map((name) => {
            const one = data.names[name];
            const beta = bench ? one?.betas[bench] : undefined;
            return [
              <strong className="pf-heat-tip-who" key={`${name}-who`}>
                {name}
              </strong>,
              <span key={`${name}-w`}>{pct(data.weights[name])}</span>,
              <span key={`${name}-v`}>{pct(one?.volatility)}</span>,
              <span key={`${name}-b`}>{beta == null ? "—" : num(beta)}</span>,
              <span key={`${name}-r`}>{pct(one?.risk_share)}</span>,
            ];
          })}
        </span>
      </>
    );
  };

  return (
    <Card title={t("portfolio.return_correlation")}>
      <Kpis
        items={[
          {
            label: t("portfolio.corr_avg"),
            value: stats.average === null ? null : num(stats.average),
            help: t("portfolio.corr_avg_help"),
            chip:
              stats.average === null
                ? null
                : { text: band(stats.average), value: null, off: true },
          },
          {
            label: t("portfolio.corr_top_pair"),
            value: stats.closest ? num(stats.closest.value) : null,
            help: t("portfolio.corr_top_pair_help"),
            chip: stats.closest
              ? {
                  text: `${stats.closest.a} × ${stats.closest.b}`,
                  value: null,
                  off: true,
                }
              : null,
          },
          {
            label: t("portfolio.corr_diversifier"),
            value: stats.diversifier?.name ?? null,
            help: t("portfolio.corr_diversifier_help"),
            chip: stats.diversifier
              ? {
                  text: t("portfolio.corr_diversifier_chip", {
                    value: num(stats.diversifier.value),
                  }),
                  value: null,
                  off: true,
                }
              : null,
          },
          {
            label: t("portfolio.corr_risk_top"),
            value: riskiest?.[0] ?? null,
            help: t("portfolio.corr_risk_top_help"),
            chip: riskiest
              ? {
                  text: t("portfolio.corr_risk_chip", {
                    share: pct(riskiest[1].risk_share),
                    weight: pct(data.weights[riskiest[0]]),
                  }),
                  value: null,
                  off: true,
                }
              : null,
          },
          ...(bench && book !== undefined
            ? [
                {
                  label: t("portfolio.corr_beta", { bench }),
                  value: num(book),
                  help: t("portfolio.corr_beta_help"),
                  chip: {
                    text: t(
                      book > 1.05
                        ? "portfolio.corr_beta_more"
                        : book < 0.95
                          ? "portfolio.corr_beta_less"
                          : "portfolio.corr_beta_even",
                    ),
                    value: null,
                    off: true,
                  },
                },
              ]
            : []),
        ]}
      />
      <Caption>{t("portfolio.corr_how")}</Caption>
      <Heatmap
        matrix={data.correlation}
        format={num}
        explain={explain}
        scale={{
          low: t("portfolio.corr_scale_low"),
          mid: t("portfolio.corr_scale_mid"),
          high: t("portfolio.corr_scale_high"),
        }}
      />
    </Card>
  );
}

/** Label-figure rows, as the chart hover boxes print them. */
function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <>
      {rows.map(([label, value]) => (
        <span className="pf-tip-row" key={label}>
          <span className="pf-muted">{label}</span>
          <strong>{value}</strong>
        </span>
      ))}
    </>
  );
}
