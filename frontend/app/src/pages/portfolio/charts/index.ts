/**
 * The page's three pictures, drawn as SVG and CSS from design tokens.
 *
 * This bundle has no charting library and is not getting one, so what a chart
 * keeps is mostly the reading: an allocation donut with its percentages on the
 * legend, a correlation grid on a diverging ramp with its −1…+1 scale under it,
 * the realized-result bars with the net as a diamond over them, and value axes
 * on all three. Two interactions: drag-to-zoom with a refitted axis on the
 * book's history, and a pointer anywhere across the plot reads the nearest day
 * (or bar) off one overlay, with a crosshair and a styled box (`ChartTip`).
 *
 * Colours come from `token()` — the `--ag-*` custom properties the server
 * inlines — so these follow both themes.
 */

export { niceTicks, plotHeightFor, AxisLabel, type TipRow } from "./frame";
export { type Slice, type SliceDetail, foldSlices, sliceTip, Donut } from "./Donut";
export {
  correlationBand,
  type CorrelationPair,
  PAIR_FLOOR,
  correlationStats,
  Heatmap,
} from "./Heatmap";
export { PeriodBars } from "./PeriodBars";
export { type WaterfallBar, Waterfall } from "./Waterfall";
export {
  type ReturnSeries,
  type LineMoney,
  lineMoney,
  dateTicks,
  ReturnLines,
} from "./ReturnLines";
export { bookTip, bookSpanTip, BookHistory } from "./BookHistory";
export { bookRatesTip, BookAndRates } from "./BookAndRates";
