/**
 * Translated strings, from the same catalogs the Streamlit pages read.
 *
 * `/api/v1/i18n/{lang}` serves them flat with English underneath, so a key the
 * translation is missing renders in English rather than as a dotted key on
 * screen. Nothing here ships a string of its own: a literal in a component is
 * a string that exists in one language, and this app has two.
 *
 * The catalog is fetched once for the whole session and held in context. It is
 * ~2300 keys, which is one request and a few tens of kilobytes — cheaper than
 * the per-page `prefix=` filtering it replaces, which cost a request per page
 * and left the shell unable to render a label before the page loaded.
 */

import { createContext, useContext, type ReactNode } from "react";
import { get } from "./api";
import { useApi } from "./useApi";

type Catalog = { lang: string; strings: Record<string, string> };

const Strings = createContext<Catalog>({ lang: "en", strings: {} });

/**
 * `t("portfolio.tab_positions")`, with `{placeholder}` slots filled in.
 *
 * A missing key renders as the key itself. That is deliberate and matches the
 * Python side: a blank is invisible in review, and a dotted key on screen is a
 * bug report that writes itself.
 */
export function useT() {
  const { strings } = useContext(Strings);
  return (key: string, slots?: Record<string, string | number>) => {
    let value = strings[key] ?? key;
    for (const [name, slot] of Object.entries(slots ?? {})) {
      value = value.replaceAll(`{${name}}`, String(slot));
    }
    return value;
  };
}

export function useLang(): string {
  return useContext(Strings).lang;
}

export function Translations({
  lang,
  children,
}: {
  lang: string;
  children: ReactNode;
}) {
  const catalog = useApi(() => get<Catalog>(`/i18n/${lang}`), [lang]);
  // A catalog that will not load must not blank the app: every key falls back
  // to itself, which is ugly and still navigable. Blocking here would turn a
  // CDN hiccup into a white screen.
  const value = catalog.state === "loaded" ? catalog.data : { lang, strings: {} };
  return <Strings.Provider value={value}>{children}</Strings.Provider>;
}
