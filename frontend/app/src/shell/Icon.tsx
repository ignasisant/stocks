/**
 * The app's icons, inline.
 *
 * No icon font. Nothing in this app's documents loads Material Symbols — a
 * `<span class="material-symbols-rounded">home</span>` here would print the
 * literal word "home" in the rail. Loading the font for eight glyphs costs a
 * request and a flash of unstyled text on every cold visit, which is the same
 * trade the ticker page already declined.
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
  filter_list: "M10 18v-2h4v2h-4zm-4-5v-2h12v2H6zM3 8V6h18v2H3z",
  swap_vert: "M16 17.01V10h-2v7.01h-3L15 21l4-3.99h-3zM9 3 5 6.99h3V14h2V6.99h3L9 3z",
  menu: "M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z",
  drag_indicator:
    "M9 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM9 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM9 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  arrow_upward: "M11 20V7.8l-5.6 5.6L4 12l8-8 8 8-1.4 1.4L13 7.8V20h-2z",
  arrow_downward: "M11 4v12.2l-5.6-5.6L4 12l8 8 8-8-1.4-1.4-5.6 5.6V4h-2z",
  add: "M11 19v-6H5v-2h6V5h2v6h6v2h-6v6h-2z",
  check: "M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z",
  auto_awesome:
    "M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L18 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z",
  forum:
    "M21 6h-2v9H6v2a1 1 0 0 0 1 1h11l4 4V7a1 1 0 0 0-1-1zm-4 6V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v14l4-4h10a1 1 0 0 0 1-1z",
  wb_sunny:
    "M6.76 4.84 4.96 3.05 3.55 4.46l1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7 1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91 1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z",
  lightbulb:
    "M9 21a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1v-1H9v1zm3-19a7 7 0 0 0-4 12.74V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.26A7 7 0 0 0 12 2z",
  search:
    "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  send: "M2.01 21 23 12 2.01 3 2 10l15 2-15 2z",
  star: "M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z",
  arrow_forward: "M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z",
  dashboard_customize:
    "M3 3h8v8H3V3zm2 2v4h4V5H5zm8-2h8v8h-8V3zm2 2v4h4V5h-4zM3 13h8v8H3v-8zm2 2v4h4v-4H5zm11-2h2v3h3v2h-3v3h-2v-3h-3v-2h3v-3z",
};

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      className="ag-icon"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}
