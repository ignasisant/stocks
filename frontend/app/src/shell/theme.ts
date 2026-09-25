/**
 * Design tokens, read back out of the CSS custom properties.
 *
 * server.py inlines `ds_vars_css()` into the document, so `--ag-*` is already
 * on `:root` before this module runs. Reading from there rather than fetching
 * /api/v1/design/tokens keeps one source at runtime: a chart colour and the
 * stylesheet rule beside it cannot disagree, and the page costs one fewer
 * round trip. (The endpoint exists for clients we do not serve the document to.)
 */

const root = () => getComputedStyle(document.documentElement);

export function token(name: string, fallback = ""): string {
  const value = root().getPropertyValue(`--ag-${name}`).trim();
  return value || fallback;
}

/** The chart palette, named as `web/ds.py` names it. */
export const chart = () => ({
  up: token("up", "#DBFFD2"),
  down: token("down", "#FFD2CB"),
  candleUp: token("candle-up", "#7ED28C"),
  candleDown: token("candle-down", "#F0897E"),
  smaFast: token("sma-fast", "#F2A33C"),
  smaSlow: token("sma-slow", "#6E8FF0"),
  smaLong: token("sma-long", "#B3AFBD"),
  info: token("info", "#7290F0"),
  brandAccent: token("brand-accent", "#A98EF7"),
  /* BRAND_ACCENT at 15% — the shaded analyst range around a forecast. */
  accentBand: token("accent-band", "rgba(169,142,247,0.15)"),
  /* BRAND_ACCENT at 22% — the top of the price line's area fade. */
  accentArea: token("accent-area", "rgba(169,142,247,0.22)"),
  warn: token("warn", "#F4C600"),
  eventLine: token("text-faint", "#696673"),
  surfacePage: token("surface-page", "#18161C"),
  surfaceCard: token("surface-card", "#28262D"),
  border: token("border", "#3B3942"),
  textPrimary: token("text-primary", "#F9F9FA"),
  textMuted: token("text-muted", "#827F8C"),
});
