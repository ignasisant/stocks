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
import {
  correlationBand,
  correlationStats,
  Heatmap,
  PAIR_FLOOR,
  type CorrelationPair,
} from "./charts";
import { TickerCell } from "../../shell/tickers";
import { decimal, percent } from "./format";
import { Caption, Card, Chip, Kpis, Lede } from "./ui";

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
              [t("portfolio.corr_tip_risk"), pct(data.names[row]?.risk_share)],
              ...(own?.peer
                ? [
                    [
                      t("portfolio.corr_tip_peer"),
                      `${own.peer.name} · ${num(own.peer.value)}`,
                    ] as [string, string],
                  ]
                : []),
            ]}
          />
        </>
      );
    }
    const combined = (data.weights[row] ?? 0) + (data.weights[column] ?? 0);
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
        <Rows rows={[[t("portfolio.corr_tip_together"), pct(combined)]]} />
        <span className="pf-heat-tip-names">
          <span className="pf-tip-head pf-heat-tip-who" />
          <span className="pf-tip-head">{t("portfolio.corr_tip_weight")}</span>
          <span className="pf-tip-head">{t("portfolio.corr_tip_risk")}</span>
          {[row, column].map((name) => {
            const one = data.names[name];
            return [
              <strong className="pf-heat-tip-who" key={`${name}-who`}>
                {name}
              </strong>,
              <span key={`${name}-w`}>{pct(data.weights[name])}</span>,
              <span key={`${name}-r`}>{pct(one?.risk_share)}</span>,
            ];
          })}
        </span>
      </>
    );
  };

  const names = Object.keys(data.correlation);
  if (names.length < 2)
    return (
      <Card title={t("portfolio.return_correlation")}>
        <Caption>{t("portfolio.corr_single")}</Caption>
      </Card>
    );

  // Which window, basis and currency the figures are in: the card's one
  // honest answer to "correlation over what?".
  const window = t(`portfolio.corr_window_${data.period}`);
  // Held names with no pair measured: too few shared days to say anything.
  const unmeasured = Object.keys(data.weights).filter(
    (name) =>
      (data.weights[name] ?? 0) > 0 &&
      !Object.entries(data.correlation[name] ?? {}).some(
        ([other, value]) => other !== name && value !== undefined,
      ),
  );
  const together = (one: CorrelationPair) => pct(one.together);
  // Pairs too small to speak for the book do not head the "diversifying" list.
  const apart = [...stats.pairs]
    .filter((one) => !stats.pairs.some((p) => p.together) || one.together >= PAIR_FLOOR)
    .sort((x, y) => x.value - y.value)
    .slice(0, 5);
  const linked = stats.pairs.slice(0, 5);
  // Bad news is red, good news green: a high average is the bad end.
  const tone = (average: number) => (average >= 0.4 ? -1 : average < 0.2 ? 1 : 0);

  const pairList = (heading: string, list: CorrelationPair[]) => (
    <div>
      <h3>{heading}</h3>
      <ol>
        {list.map((one) => (
          <li key={`${one.a}-${one.b}`}>
            <span className="pf-corr-pair">
              <TickerCell ticker={one.a} name={false} className="pf-ticker" /> ×
              <TickerCell ticker={one.b} name={false} className="pf-ticker" />
            </span>
            {one.together ? (
              <span className="pf-corr-together">
                {t("portfolio.corr_together_chip", { weight: together(one) })}
              </span>
            ) : null}
            <Chip text={`${num(one.value)} · ${band(one.value)}`} value={null} off />
          </li>
        ))}
      </ol>
    </div>
  );

  return (
    <Card title={t("portfolio.return_correlation")}>
      <Caption>{t("portfolio.corr_basis", { base: data.base, window })}</Caption>
      {stats.average !== null && stats.closest ? (
        <Lede>
          {t("portfolio.corr_verdict", {
            how: t(`portfolio.corr_verdict_${correlationBand(stats.average)}`),
            value: num(stats.average),
            pair: `${stats.closest.a} × ${stats.closest.b}`,
          })}
        </Lede>
      ) : null}
      <Kpis
        items={[
          {
            label: t("portfolio.corr_avg"),
            value: stats.average === null ? null : num(stats.average),
            help: t("portfolio.corr_avg_help"),
            chip:
              stats.average === null
                ? null
                : { text: band(stats.average), value: tone(stats.average) },
          },
          {
            label: t("portfolio.corr_top_pair"),
            value: stats.closest ? num(stats.closest.value) : null,
            help: t("portfolio.corr_top_pair_help"),
            chip: stats.closest
              ? {
                  text: stats.closest.together
                    ? `${stats.closest.a} × ${stats.closest.b} · ${together(stats.closest)}`
                    : `${stats.closest.a} × ${stats.closest.b}`,
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
        ]}
      />
      <p className="pf-corr-sub">{t("portfolio.corr_sub_risk")}</p>
      <Kpis
        items={[
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
      <div className="pf-corr-pairs">
        {pairList(t("portfolio.corr_list_linked"), linked)}
        {pairList(t("portfolio.corr_list_apart"), apart)}
      </div>
      {unmeasured.length ? (
        <Caption>
          {t("portfolio.corr_unmeasured", { names: unmeasured.join(", ") })}
        </Caption>
      ) : null}
      <details className="pf-corr-more" open={names.length <= 12}>
        <summary>{t("portfolio.corr_matrix")}</summary>
        <Caption>{t("portfolio.corr_how")}</Caption>
        <Heatmap
          matrix={data.correlation}
          format={num}
          explain={explain}
          describe={(row, column, value) =>
            row === column
              ? row
              : value === undefined
                ? `${row} × ${column}, ${t("portfolio.corr_no_overlap")}`
                : `${row} × ${column}, ${num(value)}, ${band(value)}`
          }
          scale={{
            low: t("portfolio.corr_scale_low"),
            mid: t("portfolio.corr_scale_mid"),
            high: t("portfolio.corr_scale_high"),
          }}
        />
      </details>
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
