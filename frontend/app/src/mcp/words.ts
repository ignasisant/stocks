/**
 * The view's strings and the host's theme, from what the server and the host
 * hand it — no fetch, since the frame can reach nothing but the host.
 */

import type { HostContext } from "./bridge";

/** `#ts-config`, which `connector/views.py` writes in at load. */
export type Config = {
  origin: string;
  strings: Record<string, Record<string, string>>;
};

export function readConfig(doc: Document): Config {
  const node = doc.getElementById("ts-config");
  try {
    const parsed = JSON.parse(node?.textContent ?? "") as Partial<Config>;
    return { origin: parsed.origin ?? "", strings: parsed.strings ?? {} };
  } catch {
    return { origin: "", strings: {} };
  }
}

/** The shipped language closest to the host's locale; English otherwise. */
export function language(locale: string | undefined, shipped: string[]): string {
  const want = (locale ?? "").toLowerCase().split(/[-_]/)[0] ?? "";
  if (shipped.includes(want)) return want;
  return shipped.includes("en") ? "en" : (shipped[0] ?? "en");
}

/** `{name}` slots filled in; a key with no string reads as itself. */
export function translator(strings: Record<string, string>) {
  return (key: string, slots?: Record<string, string | number>): string => {
    const text = strings[key] ?? key;
    if (!slots) return text;
    return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
      name in slots ? String(slots[name]) : whole,
    );
  };
}

/**
 * The host's look on the document: its theme as `data-theme`, its CSS
 * variables set inline so the view's `--v-*` pick them up. Only `--` names
 * are copied — anything else from a host is not a variable and not ours.
 */
export function applyTheme(root: HTMLElement, context: HostContext): void {
  if (context.theme) root.dataset.theme = context.theme;
  for (const [name, value] of Object.entries(context.styles?.variables ?? {})) {
    if (!name.startsWith("--") || typeof value !== "string") continue;
    root.style.setProperty(name, value);
  }
}
