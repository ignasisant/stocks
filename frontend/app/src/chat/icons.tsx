/**
 * The drawer's glyphs, inline.
 *
 * Same reasoning as `shell/Icon.tsx`: no icon font, because loading one for
 * eleven shapes costs a request and a flash of unstyled text on every cold
 * visit. The nav's set is not reused because none of these are in it — a rail
 * of eight page icons and a drawer of eleven controls have nothing in common
 * but the viewBox.
 *
 * Paths are Material Symbols, traced at 24px. `currentColor`, so a control's
 * own colour carries into its glyph and the design tokens stay the only place
 * a colour is decided.
 */

const PATHS: Record<string, string> = {
  spark:
    "M12 2l1.8 4.9L18.7 8.7l-4.9 1.8L12 15.4l-1.8-4.9L5.3 8.7l4.9-1.8L12 2zm5.5 11l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2zM6 14l.7 1.9 1.9.7-1.9.7L6 19.2l-.7-1.9-1.9-.7 1.9-.7L6 14z",
  close:
    "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  add: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5z",
  forum: "M4 3h13a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8l-4 4V3zm2 2v9.2L7.2 13H17V5H6z",
  back: "M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z",
  search:
    "M10 3a7 7 0 0 1 5.5 11.3l4.6 4.6-1.4 1.4-4.6-4.6A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10z",
  edit: "M3 17.2V21h3.8L17.8 10 14 6.2 3 17.2zM20.7 7.1a1 1 0 0 0 0-1.4l-2.4-2.4a1 1 0 0 0-1.4 0l-1.8 1.8L18.9 8.9l1.8-1.8z",
  trash: "M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
  link: "M3.9 12A3.1 3.1 0 0 1 7 8.9h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8v2zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z",
  globe:
    "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM4.3 14a8 8 0 0 1 0-4h3.3a16.5 16.5 0 0 0 0 4H4.3zm.8 2h2.9c.3 1.3.8 2.5 1.4 3.6A8 8 0 0 1 5.1 16zm2.9-8H5.1a8 8 0 0 1 4.3-3.6C8.8 5.5 8.3 6.7 8 8zM12 20c-.8-1.2-1.4-2.5-1.8-4h3.6c-.4 1.5-1 2.8-1.8 4zm2.2-6H9.8a14.7 14.7 0 0 1 0-4h4.4a14.7 14.7 0 0 1 0 4zM12 4c.8 1.2 1.4 2.5 1.8 4h-3.6c.4-1.5 1-2.8 1.8-4zm2.6 15.6c.6-1.1 1.1-2.3 1.4-3.6h2.9a8 8 0 0 1-4.3 3.6zM16.4 14a16.5 16.5 0 0 0 0-4h3.3a8 8 0 0 1 0 4h-3.3zm-.8-6c-.3-1.3-.8-2.5-1.4-3.6A8 8 0 0 1 18.9 8h-3.3z",
  send: "M12 4l6.5 6.5-1.4 1.4-4.1-4.1V20h-2V7.8l-4.1 4.1L5.5 10.5 12 4z",
  down: "M20 12l-1.4-1.4L13 16.2V4h-2v12.2l-5.6-5.6L4 12l8 8 8-8z",
  settings:
    "M19.14 12.94a7.07 7.07 0 0 0 0-1.88l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7 7 0 0 0-1.62-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54c-.59.24-1.13.56-1.62.94l-2.39-.96a.5.5 0 0 0-.6.22L2.67 8.84a.5.5 0 0 0 .12.64l2.03 1.58a7.07 7.07 0 0 0 0 1.88l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.12.22.38.3.6.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.04.24.25.42.5.42h3.84c.25 0 .46-.18.5-.42l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.48 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.6a3.6 3.6 0 1 1 0-7.2 3.6 3.6 0 0 1 0 7.2z",
  stop: "M8 7h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z",
  refresh: "M12 6V3L8 7l4 4V8a4 4 0 1 1-4 4H6a6 6 0 1 0 6-6z",
  mic: "M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-4 4.9V20h3v2H8v-2h3v-4.1A5 5 0 0 1 7 11h2a3 3 0 0 0 6 0h2z",
  attach:
    "M16.5 6.5v9.75a4.25 4.25 0 0 1-8.5 0V5.5a2.75 2.75 0 0 1 5.5 0v9.75a1.25 1.25 0 0 1-2.5 0V6.5H9.5v8.75a2.75 2.75 0 0 0 5.5 0V5.5a4.25 4.25 0 0 0-8.5 0v10.75a5.75 5.75 0 0 0 11.5 0V6.5h-1.5z",
  key: "M21 10h-8.35A5.99 5.99 0 0 0 7 6a6 6 0 1 0 5.65 8H13l2 2 2-2 2 2 3-3.05L21 10zM7 15a3 3 0 1 1 0-6 3 3 0 0 1 0 6z",
  // The three width presets, in the order they widen. The frame says how much
  // room the panel takes; the arrows inside it say which way the press moves.
  width_normal: "M7 4h10v16H7V4zm2 2v12h6V6H9z",
  width_wide: "M3 4h18v16H3V4zm2 2v12h14V6H5zm4 3 3 3-3 3V9zm6 0v6l-3-3 3-3z",
  fullscreen:
    "M4 4h6v2H6v4H4V4zm10 0h6v6h-2V6h-4V4zM4 14h2v4h4v2H4v-6zm14 0h2v6h-6v-2h4v-4z",
};

export function Glyph({ name, size = 18 }: { name: string; size?: number }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      className="ag-chat-glyph"
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

/**
 * The four line icons on the opening screen, in the order the capability rows
 * name them: what you hold, the web, an import, an alert. Stroked rather than
 * filled, which is how the artboard draws them.
 */
export const CAP_PATHS = [
  "M21.2 15.9A10 10 0 1 1 8 2.8 M22 12A10 10 0 0 0 12 2v10z",
  "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z M3.5 12h17 M12 3.5c3 3.5 3 13.5 0 17 M12 3.5c-3 3.5-3 13.5 0 17",
  "M12 3v12 M7 10l5 5 5-5 M3 21h18",
  "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9 M10 21h4",
];

export function CapGlyph({ paths }: { paths: string }) {
  return (
    <svg
      className="ag-chat-capicon"
      viewBox="0 0 24 24"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      focusable="false"
    >
      {paths.split(" M").map((part, i) => (
        <path d={i ? `M${part}` : part} key={i} />
      ))}
    </svg>
  );
}
