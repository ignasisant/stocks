/**
 * What it is worth, in one frame, and how its multiples sit against the
 * rivals'.
 *
 * Three ways to value a name — the DCF, the street's targets, the rivals'
 * P/E — used to be three cards that disagreed without saying why. Here they
 * share one axis with the price at zero, and the reason they differ is the
 * assumption each one rests on, read off the figures the page already holds.
 * Nothing is computed that the cards below do not show (`worthmath.ts`).
 */

import { useT } from "../../shell/i18n";
import { DASH, money, percent } from "../../shell/format";
import { Card, Note } from "./ui";
import type { Analysts, Comparables, Dcf } from "./types";
import { peerBars, worthAxis, worthRows, type WorthRow } from "./worthmath";

const pct = (fraction: number) =>
  percent(fraction, { digits: 0, signed: "always", tight: true }) ?? DASH;

export function WorthSection({
  dcf,
  analysts,
  comps,
}: {
  dcf?: Dcf | null;
  analysts?: Analysts | null;
  comps?: Comparables | null;
}) {
  const t = useT();
  const rows = worthRows(dcf ?? null, analysts ?? null, comps ?? null);
  if (rows.length === 0) return null;
  const { lo, hi } = worthAxis(rows);
  const at = (value: number) => `${((value - lo) / (hi - lo)) * 100}%`;
  const median = comps?.peer_median[comps.keys?.indexOf("pe_ttm") ?? -1] ?? "";

  const why = rows.map((one) => {
    switch (one.id) {
      case "dcf":
        return t("ticker.worth_why_dcf", {
          growth: Math.round((dcf?.growth ?? 0) * 1000) / 10,
          wacc: Math.round((dcf?.wacc ?? 0) * 1000) / 10,
        });
      case "analysts":
        return t("ticker.worth_why_analysts", { n: analysts?.analysts ?? 0 });
      case "peers":
        return t("ticker.worth_why_peers", { median });
    }
  });

  return (
    <Card title={t("ticker.worth_title")} note={t("ticker.worth_note")}>
      <div className="tk-worth" role="list">
        {rows.map((one) => (
          <WorthLine key={one.id} one={one} at={at} />
        ))}
        <div className="tk-worth-axis" aria-hidden="true">
          <span className="tk-worth-price" style={{ left: at(0) }}>
            {t("ticker.worth_price")}
          </span>
        </div>
      </div>
      {rows.length > 1 ? (
        <Note>
          <strong>{t("ticker.worth_why_head")}</strong> {why.join(" ")}{" "}
          {t("ticker.worth_why_close")}
        </Note>
      ) : null}
    </Card>
  );
}

function WorthLine({ one, at }: { one: WorthRow; at: (value: number) => string }) {
  const t = useT();
  const tone = one.at >= 0 ? "up" : "down";
  const from = Math.min(0, one.at);
  const to = Math.max(0, one.at);
  const figure =
    one.value === null
      ? ""
      : `${money(one.value, { digits: 2 }) ?? DASH}${one.currency ? ` ${one.currency}` : ""}`;
  return (
    <div className="tk-worth-row" role="listitem">
      <span className="tk-worth-name">{t(`ticker.worth_${one.id}`)}</span>
      <span className="tk-worth-track">
        <span className="tk-worth-zero" style={{ left: at(0) }} />
        {one.low !== undefined && one.high !== undefined ? (
          <span
            className="tk-worth-range"
            style={{
              left: at(one.low),
              width: `calc(${at(one.high)} - ${at(one.low)})`,
            }}
            title={t("ticker.worth_range", { low: pct(one.low), high: pct(one.high) })}
          />
        ) : null}
        <span
          className={`tk-worth-reach tk-worth-${tone}`}
          style={{ left: at(from), width: `calc(${at(to)} - ${at(from)})` }}
        />
        <span
          className={`tk-worth-dot tk-worth-${tone}`}
          style={{ left: at(one.at) }}
        />
      </span>
      <span className="tk-worth-read">
        <strong className={`tk-is-${one.at >= 0 ? "green" : "red"}`}>
          {pct(one.at)}
        </strong>
        {figure ? <small>{figure}</small> : null}
      </span>
    </div>
  );
}

/**
 * The name's multiples as bars against the median of the rivals', each row
 * on its own scale: a bar is read against its own tick, never against the
 * next row's unit.
 */
export function PeerBars({ comps }: { comps: Comparables | null }) {
  const t = useT();
  const bars = peerBars(comps);
  if (!comps || bars.length === 0) return null;
  return (
    <Card
      title={t("ticker.peers_title")}
      note={t("ticker.peers_note", { n: comps.tickers.length - 1 })}
    >
      <div className="tk-peerbars" role="list">
        {bars.map((one) => (
          <div className="tk-peerbar" role="listitem" key={one.key}>
            <span className="tk-peerbar-label">{one.label}</span>
            <span className="tk-peerbar-track">
              <span
                className={`tk-peerbar-fill tk-worth-${one.better ? "up" : "warn"}`}
                style={{ width: `${one.mineWidth * 100}%` }}
              />
              <span
                className="tk-peerbar-median"
                style={{ left: `${one.medianAt * 100}%` }}
                title={t("ticker.peers_median")}
              />
            </span>
            <span className="tk-peerbar-read">
              <strong>{one.mineText}</strong>
              <small>
                {t("ticker.peers_vs", { median: one.medianText })}
                <span className="ag-sr">
                  {" "}
                  {one.better ? t("ticker.peers_better") : t("ticker.peers_worse")}
                </span>
              </small>
            </span>
          </div>
        ))}
      </div>
      <ul className="tk-legend tk-legend-wrap">
        <li>
          <span className="tk-swatch tk-worth-up" />
          <span>{t("ticker.peers_better")}</span>
        </li>
        <li>
          <span className="tk-swatch tk-worth-warn" />
          <span>{t("ticker.peers_worse")}</span>
        </li>
        <li>
          <span className="tk-peerbar-tick" />
          <span>{t("ticker.peers_median")}</span>
        </li>
      </ul>
    </Card>
  );
}
