/** The short-selling card draws what a source gave and nothing for a miss. */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ShortsSection } from "./Sections";
import type { Shorts } from "./types";

const base: Shorts = { ticker: "X", us: null, eu: null };

describe("ShortsSection", () => {
  it("draws nothing when no source covers the name", () => {
    expect(renderToStaticMarkup(<ShortsSection shorts={base} />)).toBe("");
  });

  it("lists EU holders with the total", () => {
    const html = renderToStaticMarkup(
      <ShortsSection
        shorts={{
          ...base,
          eu: {
            source: "AFM",
            issuer: "Akzo",
            total_pct: 3.3,
            as_of: "2026-10-23",
            holders: [{ name: "Millennium LP", pct: 1.61, date: "2026-10-23" }],
            holders_count: 1,
          },
        }}
      />,
    );
    expect(html).toContain("Millennium LP");
  });

  it("draws no table when the FCA gives only a total", () => {
    const html = renderToStaticMarkup(
      <ShortsSection
        shorts={{
          ...base,
          eu: {
            source: "FCA",
            issuer: "BAE",
            total_pct: 0.2,
            as_of: null,
            holders: [],
            holders_count: 0,
          },
        }}
      />,
    );
    expect(html).not.toContain("<table");
  });

  it("shows US short interest with volume missing", () => {
    const html = renderToStaticMarkup(
      <ShortsSection
        shorts={{
          ...base,
          us: {
            pct_float: 6.45,
            shares_short: null,
            days_to_cover: 2.3,
            change_pct: null,
            as_of: null,
            volume_ratio: null,
            volume_days: null,
            volume_as_of: null,
          },
        }}
      />,
    );
    expect(html).toContain("6");
  });
});
