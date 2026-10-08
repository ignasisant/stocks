/**
 * The moat card words its pillars in the reader's language from the facts the
 * API hands over, and falls back to the API's English when the catalog lacks a
 * key — never to the key itself.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MoatSection, moatDetail } from "./Sections";
import type { Moat, MoatPillar } from "./types";

const roic: MoatPillar = {
  key: "roic",
  label: "ROIC",
  label_key: "ticker.moat_pillar_roic",
  score: 100,
  tone: "green",
  weight: 0.3,
  detail: "median ROIC 47%, ≥10% in 4/4 years",
  detail_key: "ticker.moat_detail_roic",
  facts: { roic: 0.47, above: 4, years: 4 },
};

const dilution: MoatPillar = {
  key: "dilution",
  label: "Dilution",
  label_key: "ticker.moat_pillar_dilution",
  score: null,
  tone: null,
  weight: 0.15,
  detail: "diluted share history missing",
  detail_key: "ticker.moat_detail_missing",
  facts: {},
};

const moat: Moat = {
  ticker: "AAPL",
  score: 88,
  rating: "wide",
  rating_key: "ticker.moat_rating_wide",
  rating_tone: "green",
  years: 4,
  pillars: [roic, dilution],
};

/** A catalog of two entries, filled the way the shell's `t` fills them. */
const t = (key: string, values?: Record<string, string | number>) => {
  const catalog: Record<string, string> = {
    "ticker.moat_detail_roic": "ROIC mediano {roic}, ≥10% en {above} de {years} años",
    "ticker.moat_detail_dilution": "Acciones {shares} al año",
    "ticker.moat_detail_op_margin":
      "{margin}; oscila {sd} p. p. y ha variado {change} p. p.",
  };
  const text = catalog[key];
  if (!text) return key;
  return text.replace(/\{(\w+)\}/g, (_, name) => String(values?.[name] ?? ""));
};

describe("moatDetail", () => {
  it("words a pillar from its facts", () => {
    expect(moatDetail(t, roic)).toBe("ROIC mediano 47%, ≥10% en 4 de 4 años");
  });

  it("prints a share count change signed", () => {
    const shares = {
      ...dilution,
      detail_key: "ticker.moat_detail_dilution",
      facts: { shares: -0.066 },
    };
    expect(moatDetail(t, shares)).toBe("Acciones -6.6% al año");
  });

  it("prints margin swings in points, a drift too small to show as +0.0", () => {
    const margin = {
      ...roic,
      detail_key: "ticker.moat_detail_op_margin",
      facts: { margin: 0.032, sd: 0.0021, change: -0.00004 },
    };
    expect(moatDetail(t, margin)).toBe("3%; oscila 0.2 p. p. y ha variado +0.0 p. p.");
    const fell = { ...margin, facts: { ...margin.facts, change: -0.031 } };
    expect(moatDetail(t, fell)).toContain("-3.1 p. p.");
  });

  it("falls back to the API's English, not the key", () => {
    expect(moatDetail(t, { ...roic, detail_key: "ticker.nope" })).toBe(roic.detail);
  });
});

describe("MoatSection", () => {
  it("draws a toned bar for a scored pillar and none for an unscored one", () => {
    const html = renderToStaticMarkup(<MoatSection moat={moat} />);
    expect(html).toContain("tk-bar-up");
    expect(html.match(/tk-bar-fill/g)).toHaveLength(1);
    expect(html).toContain("tk-moat");
  });
});
