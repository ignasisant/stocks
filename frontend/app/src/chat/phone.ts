/**
 * Whether the app is laid out for a phone: the tab bar, a full-width drawer.
 *
 * The same 640px line as every `@media (max-width: 640px)` in the stylesheets,
 * read as state so a component can draw a different thing there and not just
 * a differently sized one — the import's touch list, the header's menu.
 * Followed as it changes, since a tablet turned on its side crosses it.
 */

import { useEffect, useState } from "react";

const QUERY = "(max-width: 640px)";

function matches(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(QUERY).matches;
}

export function usePhone(): boolean {
  const [phone, setPhone] = useState(matches);
  useEffect(() => {
    const media = window.matchMedia?.(QUERY);
    if (!media) return;
    const follow = () => setPhone(media.matches);
    follow();
    media.addEventListener?.("change", follow);
    return () => media.removeEventListener?.("change", follow);
  }, []);
  return phone;
}
