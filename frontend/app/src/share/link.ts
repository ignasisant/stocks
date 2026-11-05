/**
 * What every share in the app is made of: a link on this origin that credits
 * the visit it brings, a line of text in the sharer's voice, and the
 * platforms' own share links.
 *
 * `src=share` names the visit a share's (`attribution.py`), and `medium` which
 * kind of thing was shared — an answer, a ticker, an invite — so the share
 * funnel (`stocks logs shares`) can say which of them bring people. Both are
 * passive parameters: they survive the sign-in and change nothing on the page.
 */

/** Past this a line of text is cut on a word: on X it is all the post says. */
const TEXT_MAX = 100;

/** `path` on this origin, as an address to send. */
export function absolute(path: string): string {
  return new URL(path, window.location.origin).toString();
}

/** `path` on this origin, credited to a share of kind `medium`. */
export function sharedLink(path: string, medium?: string): string {
  const url = new URL(absolute(path));
  url.searchParams.set("src", "share");
  if (medium) url.searchParams.set("medium", medium);
  return url.toString();
}

export function clip(text: string, max = TEXT_MAX): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max - 1);
  return `${cut.slice(0, cut.lastIndexOf(" ") > 40 ? cut.lastIndexOf(" ") : cut.length)}…`;
}

/** The platforms, as the links their own share buttons open. */
export function destinations(
  url: string,
  text: string,
): { id: string; label: string; href: string }[] {
  const u = encodeURIComponent(url);
  const said = encodeURIComponent(text);
  return [
    { id: "whatsapp", label: "WhatsApp", href: `https://wa.me/?text=${said}%20${u}` },
    { id: "x", label: "X", href: `https://x.com/intent/post?text=${said}&url=${u}` },
    {
      id: "linkedin",
      label: "LinkedIn",
      href: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
    },
    {
      id: "telegram",
      label: "Telegram",
      href: `https://t.me/share/url?url=${u}&text=${said}`,
    },
    {
      id: "facebook",
      label: "Facebook",
      href: `https://www.facebook.com/sharer/sharer.php?u=${u}`,
    },
    { id: "email", label: "Email", href: `mailto:?subject=${said}&body=${u}` },
  ];
}

/**
 * Whether a share should go straight to the device's own sheet: on a phone
 * it is where WhatsApp and the rest already are, and a dialog of our own in
 * front of it is a step for nothing. A desktop's sheet is thin, so there the
 * dialog with the platforms comes first.
 */
export function nativeFirst(): boolean {
  return (
    typeof navigator !== "undefined" &&
    "share" in navigator &&
    window.matchMedia?.("(pointer: coarse)").matches === true
  );
}
