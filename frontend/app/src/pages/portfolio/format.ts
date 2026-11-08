/**
 * Numbers into strings, with one rule running through all of it: a value the
 * API sent as `null` comes back as `null` here too, never as "0" and never as
 * a formatted zero. The caller renders `t("portfolio.na")` in its place.
 *
 * Amounts go through `Intl.NumberFormat` in the account's own language, so a
 * Spanish reader gets "1.234 €" and an English one "€1,234".
 */

import { isNum } from "../../shell/format";

type Maybe = number | null | undefined;

/** Sign of a figure, for the colour a P/L cell takes. `null` is neither. */
export function tone(value: Maybe): "up" | "down" | "flat" {
  if (!isNum(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * The flag for a jurisdiction code, built from the code rather than a table,
 * including the one code that is not ISO 3166-1 alpha-2.
 */
function flagOf(code: string): string {
  const alpha2 = code.toUpperCase() === "UK" ? "GB" : code.toUpperCase();
  if (alpha2.length !== 2 || !/^[A-Z]{2}$/.test(alpha2)) return "";
  return [...alpha2]
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join("");
}

/** "🇪🇸 Spain — IRPF": the flag built from the code, the name from the catalog. */
export function jurisdictionLabel(code: string, t: (key: string) => string): string {
  return `${flagOf(code)} ${t(`profile.tax_residence_${code.toLowerCase()}`)}`.trim();
}

/** Display names for a ledger broker prefix — `portfolio/platforms.py`. */
const BROKER_NAMES: Record<string, string> = {
  revolut: "Revolut",
  trading212: "Trading 212",
  degiro: "DEGIRO",
  ibkr: "IBKR",
  clicktrade: "ClickTrade",
  saxo: "Saxo",
  // platforms.CRYPTO_EXCHANGES — only the ones title-casing gets wrong.
  crypto_com: "Crypto.com",
  kucoin: "KuCoin",
  bit2me: "Bit2Me",
  okx: "OKX",
  etoro: "eToro",
  cointracking: "CoinTracking",
};

/**
 * "clicktrade" -> "ClickTrade". The two generic buckets — a hand-entered row
 * and a holding no note attributes — are localized instead; everything else is
 * a brand name, which is the same word in both languages.
 */
export function brokerName(key: string, t: (k: string) => string): string {
  if (key === "manual") return t("portfolio.broker_manual");
  // platforms.OTHER: a real origin the registry does not parse.
  if (key === "other") return t("portfolio.broker_other");
  if (key === "unknown" || key === "") return t("portfolio.broker_unknown");
  return (
    BROKER_NAMES[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}
