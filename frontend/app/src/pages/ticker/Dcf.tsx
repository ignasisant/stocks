/**
 * The DCF card: what the price implies against a plain five-year cash-flow
 * model, with its assumptions on the page and editable.
 *
 * It is an illustration of the inputs, never a recommendation, and it blanks
 * with a one-line reason for the businesses it cannot value honestly (no
 * positive free cash flow; a bank, REIT or utility, whose FCF is not owner
 * cash). Edits recompute here (`dcf.ts`, mirrored from the Python), so the
 * grid under it always shows the assumptions above it.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { valuePerShare } from "./dcfmath";
import { DASH, money, signedPercent } from "./format";
import { Card, Note, Scroll } from "./ui";
import type { Dcf } from "./types";

/** A percentage as the field shows it: 0.085 -> "8.5". */
const asField = (rate: number) => String(Math.round(rate * 1000) / 10);
/** …and back; NaN for what is not a number yet. */
const asRate = (field: string) => (field.trim() === "" ? NaN : Number(field) / 100);
const same = (a: number, b: number) => Math.abs(a - b) < 1e-9;

export function DcfSection({ dcf }: { dcf: Dcf }) {
  const t = useT();
  const [growth, setGrowth] = useState(asField(dcf.growth ?? 0));
  const [wacc, setWacc] = useState(asField(dcf.wacc));
  const [terminal, setTerminal] = useState(asField(dcf.terminal));

  if (dcf.reason || dcf.fcf === null || dcf.net_debt === null || dcf.shares === null) {
    return (
      <Card fold="dcf" title={t("ticker.dcf")}>
        <Note>{t(`ticker.dcf_reason_${dcf.reason ?? "no_data"}`)}</Note>
      </Card>
    );
  }
  const { fcf, net_debt: netDebt, shares } = dcf;
  const g = asRate(growth);
  const w = asRate(wacc);
  const tg = asRate(terminal);
  const value = [g, w, tg].some(Number.isNaN)
    ? null
    : valuePerShare(fcf, g, w, tg, netDebt, shares);
  const upside = value !== null && dcf.price ? value / dcf.price - 1 : null;
  const edited =
    !same(g, dcf.growth ?? 0) || !same(w, dcf.wacc) || !same(tg, dcf.terminal);
  const grid = dcf.waccs.map((rowW) =>
    dcf.terminals.map((colG) =>
      Number.isNaN(g) ? null : valuePerShare(fcf, g, rowW, colG, netDebt, shares),
    ),
  );

  const field = (key: string, label: string, val: string, set: (v: string) => void) => (
    <label className="tk-dcf-field" key={key}>
      <span>{label}</span>
      <span className="tk-dcf-input">
        <input
          type="number"
          inputMode="decimal"
          step={0.5}
          value={val}
          onChange={(e) => set(e.target.value)}
        />
        %
      </span>
    </label>
  );

  return (
    <Card fold="dcf" title={t("ticker.dcf")} note={t("ticker.dcf_help")}>
      <div className="tk-dcf-head">
        <div className="tk-dcf-value">
          <span className="tk-dcf-label">{t("ticker.dcf_value")}</span>
          <strong>
            {value === null ? DASH : money(value)} {dcf.currency ?? ""}
          </strong>
          <span className="tk-dcf-vs">
            {upside === null
              ? t("ticker.dcf_refused")
              : t("ticker.dcf_vs_price", {
                  price: money(dcf.price),
                  pct: signedPercent(upside, 0),
                })}
          </span>
        </div>
        <div className="tk-dcf-inputs">
          {field("g", t("ticker.dcf_growth"), growth, setGrowth)}
          {field("w", t("ticker.dcf_wacc"), wacc, setWacc)}
          {field("t", t("ticker.dcf_terminal"), terminal, setTerminal)}
          {edited ? (
            <button
              type="button"
              className="tk-dcf-reset"
              onClick={() => {
                setGrowth(asField(dcf.growth ?? 0));
                setWacc(asField(dcf.wacc));
                setTerminal(asField(dcf.terminal));
              }}
            >
              {t("ticker.dcf_reset")}
            </button>
          ) : null}
        </div>
      </div>
      <Note>
        {t(`ticker.dcf_growth_${dcf.growth_source ?? "fallback"}`, {
          growth: asField(dcf.growth ?? 0),
        })}
      </Note>
      <Scroll>
        <table className="tk-table tk-dcf-grid">
          <caption className="tk-dcf-cap">{t("ticker.dcf_grid")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("ticker.dcf_wacc")}</th>
              {dcf.terminals.map((colG) => (
                <th scope="col" key={colG}>
                  {asField(colG)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dcf.waccs.map((rowW, i) => (
              <tr key={rowW}>
                <th scope="row">{asField(rowW)}%</th>
                {dcf.terminals.map((colG, j) => {
                  const cell = grid[i]?.[j] ?? null;
                  const current = same(rowW, w) && same(colG, tg);
                  return (
                    <td
                      key={colG}
                      className={current ? "tk-dcf-now" : undefined}
                      aria-current={current ? "true" : undefined}
                    >
                      {cell === null ? DASH : money(cell)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </Card>
  );
}
