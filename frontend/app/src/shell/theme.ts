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
  warnOrange: token("warn-orange", "#EF752E"),
  eventLine: token("text-faint", "#696673"),
  surfacePage: token("surface-page", "#18161C"),
  surfaceCard: token("surface-card", "#28262D"),
  border: token("border", "#3B3942"),
  textPrimary: token("text-primary", "#F9F9FA"),
  textSecondary: token("text-secondary", "#B3AFBD"),
  textMuted: token("text-muted", "#A09DAA"),
});

/**
 * Series identity, `ds.py`'s `CATEGORICAL_COLORS` in its order. Fixed, never
 * cycled: series past the fifth take `seriesOther`, and a chart keeps each
 * entity on the same slot however the set is filtered.
 */
export const series = (): string[] => [
  token("series-1", "#4C8DFF"),
  token("series-2", "#E0662A"),
  token("series-3", "#8B6CF0"),
  token("series-4", "#C08400"),
  token("series-5", "#C54EA4"),
];

/** The folded tail — "Others" in a ring, any line past the fifth. */
export const seriesOther = () => token("series-other", "#A09DAA");

/** Index lines keep one slot on every chart, so SPY reads as SPY on the Risk
 *  tab and in a ticker's Compare alike. */
const INDEX_SLOT: Record<string, number> = { SPY: 0, EEM: 1, QQQ: 3 };

/** The slots any other name takes, the ones no index claims first. */
const FREE_ORDER = [2, 4, 0, 1, 3];

/**
 * A series hue per name. An index takes its own slot; any other name keeps
 * the hue it had in `kept` (the last render's map), else the first free slot.
 * So dropping one line never repaints the rest, and a sixth name past the
 * palette is `seriesOther`, not a repeat.
 */
export function seriesColors(
  names: readonly string[],
  kept: Readonly<Record<string, string>> = {},
): Record<string, string> {
  const hues = series();
  const out: Record<string, string> = {};
  const taken = new Set<string>();
  const claim = (name: string, hue: string | undefined) => {
    if (hue === undefined || !hues.includes(hue) || taken.has(hue)) return;
    out[name] = hue;
    taken.add(hue);
  };
  for (const name of names) {
    const slot = INDEX_SLOT[name];
    if (slot !== undefined) claim(name, hues[slot]);
  }
  for (const name of names) if (!(name in out)) claim(name, kept[name]);
  for (const name of names) {
    if (name in out) continue;
    const free = FREE_ORDER.map((slot) => hues[slot]).find(
      (hue) => hue !== undefined && !taken.has(hue),
    );
    if (free === undefined) out[name] = seriesOther();
    else claim(name, free);
  }
  return out;
}
