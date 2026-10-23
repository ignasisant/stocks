/**
 * The DCF card's arithmetic, mirroring `stocks.analysis.dcf.value_per_share`
 * so an input edited on the page re-values it without a round trip.
 *
 * `dcf.fixture.json` is shared with the Python tests: both sides must agree on
 * every row, to 1e-9.
 */

const YEARS = 5;

/**
 * Equity value per share: `years` flows grown at `growth`, then the Gordon
 * terminal value at the last one, all discounted at `wacc`, less net debt,
 * over diluted shares. Null where the maths has no answer: a non-positive base
 * or share count, or terminal growth at or above the discount rate.
 */
export function valuePerShare(
  fcf: number,
  growth: number,
  wacc: number,
  terminal: number,
  netDebt: number,
  shares: number,
  years: number = YEARS,
): number | null {
  if (fcf <= 0 || shares <= 0 || wacc <= 0 || terminal >= wacc || growth <= -1) {
    return null;
  }
  let pv = 0;
  let flow = fcf;
  for (let year = 1; year <= years; year++) {
    flow *= 1 + growth;
    pv += flow / (1 + wacc) ** year;
  }
  pv += (flow * (1 + terminal)) / (wacc - terminal) / (1 + wacc) ** years;
  return (pv - netDebt) / shares;
}
