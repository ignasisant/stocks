/**
 * The nav's icons, inline.
 *
 * No icon font. Streamlit renders `:material/home:` itself, so nothing in this
 * app's documents ever loads Material Symbols — a `<span class="material-
 * symbols-rounded">home</span>` here would print the literal word "home" in the
 * rail. Loading the font for eight glyphs costs a request and a flash of
 * unstyled text on every cold visit, which is the same trade the ticker page
 * already declined.
 *
 * Paths are Material Symbols, traced at 24px and simplified. `currentColor` so
 * a nav item's own colour carries into the glyph and the design tokens stay the
 * only place a colour is decided.
 */

const PATHS: Record<string, string> = {
  home: "M4 21V10l8-6 8 6v11h-6v-6h-4v6H4z",
  pie_chart:
    "M11 3.06V11H3.06A9 9 0 0 1 11 3.06zM13 3.06A9 9 0 0 1 20.94 11H13V3.06zM3.06 13H12l6.31 6.31A9 9 0 0 1 3.06 13z",
  speed:
    "M12 4a9 9 0 0 1 7.79 13.5H4.21A9 9 0 0 1 12 4zm.7 5.3-3.4 5.1a1 1 0 0 0 1.4 1.4l5.1-3.4a.5.5 0 0 0-.6-.8l-2.5 1.7z",
  donut_small:
    "M11 3.06A9 9 0 0 0 3.06 11H8a4 4 0 0 1 3-3.87V3.06zM13 3.06v4.07A4 4 0 0 1 16 11h4.94A9 9 0 0 0 13 3.06zM3.06 13A9 9 0 0 0 11 20.94V16a4 4 0 0 1-3-3H3.06zM16 13a4 4 0 0 1-3 3v4.94A9 9 0 0 0 20.94 13H16z",
  calendar_month:
    "M7 2v2h10V2h2v2h1a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1V2h2zM4 9v10h16V9H4zm3 2h3v3H7v-3z",
  upload_file:
    "M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-7-7zm-1 2 6 6h-6V4zm-1 8 3.5 3.5-1.4 1.4-1.1-1.1V20h-2v-4.2l-1.1 1.1L7.5 15.5 11 12z",
  account_circle:
    "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a3 3 0 1 1 0 6 3 3 0 0 1 0-6zm0 14a7.9 7.9 0 0 1-5.6-2.3c.6-1.9 3-3 5.6-3s5 1.1 5.6 3A7.9 7.9 0 0 1 12 20z",
  query_stats: "M4 20V10h3v10H4zm6.5 0V4h3v16h-3zM17 20v-7h3v7h-3z",
  menu: "M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z",
};

export function Icon({ name }: { name: string }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      className="ag-icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}
