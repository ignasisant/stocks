/**
 * The drawer's own marks: a provider's logo and the opening screen's four
 * line icons. The filled glyphs every control wears are `ui/Glyph`.
 */

import { Glyph } from "../ui/Glyph";

/**
 * A provider's brand mark: its logo over its initial, so a logo that fails to
 * load leaves a letter rather than a hole — the import page's platform chips
 * do the same. The keyless chain is this app's own and wears the drawer's
 * spark. Decorative either way: the name beside it is the label.
 */
export function ProviderMark({
  provider,
}: {
  provider: { label: string; logo?: string | null; needs_key: boolean };
}) {
  return (
    <span
      aria-hidden="true"
      className={`ag-chat-mark${provider.needs_key ? "" : " ag-chat-mark-own"}`}
    >
      {provider.needs_key ? (
        provider.label.charAt(0).toUpperCase()
      ) : (
        <Glyph name="spark" />
      )}
      {provider.logo && (
        <img
          alt=""
          src={provider.logo}
          loading="lazy"
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      )}
    </span>
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
