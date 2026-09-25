/**
 * What the "why" rows and the book card draw from a given payload.
 *
 * Two parity claims with the Streamlit page, each easy to regress silently:
 * the input rows print the raw reading the server formatted (+4.2%, 15.2),
 * never the 0-100 score the bar already encodes; and the book card carries all
 * the betas Streamlit's does — equity, duration, credit, emerging markets —
 * each with its own drift pill.
 *
 * Rendered to static markup, with no catalog loaded, so every label prints as
 * its key — which is exactly what makes the tiles countable here.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Book } from "./Book";
import { Composite, Side } from "./Hero";
import { Snapshot } from "./Snapshot";
import { Why } from "./Why";
import type { Pulse, PulseBook } from "./types";

const pulse: Pulse = {
  score: 64,
  regime: "appetite",
  as_of: "2026-09-23",
  run: 3,
  components: [
    { key: "momentum", score: 81, raw: 0.042, text: "+4.2%", then: 60 },
    { key: "volatility", score: 55, raw: 15.2, text: "15.2", then: null },
  ],
  missing: ["credit"],
  history: [],
  breadth_indices: null,
  breadth_sectors: null,
  stock_bond_correlation: null,
  stock_bond_correlation_then: null,
  loaded_at: "2026-09-24 08:00 UTC",
};

const book: PulseBook = {
  base: "EUR",
  beta: 1.12,
  beta_rolling: 1.2,
  beta_rolling_then: 0.9,
  stance: "amplify",
  bond_correlation: 0.1,
  bond_correlation_then: -0.2,
  usd_share: 0.7,
  fx_drag: -0.01,
  currency_weights: { USD: 0.7, EUR: 0.3 },
  rotation_capture: null,
  sector_tilt: {},
  betas: [
    { key: "duration", ticker: "TLT", beta: -0.31, rolling: -0.2, rolling_then: -0.4 },
    { key: "credit", ticker: "HYG", beta: 0.84, rolling: 0.8, rolling_then: 0.79 },
    { key: "em", ticker: "EEM", beta: null, rolling: null, rolling_then: null },
  ],
};

describe("why rows", () => {
  it("print the raw reading, not the score", () => {
    const html = renderToStaticMarkup(<Why pulse={pulse} />);
    expect(html).toContain(">+4.2%<");
    expect(html).toContain(">15.2<");
    expect(html).not.toContain(">81<");
  });
});

describe("book card", () => {
  it("carries every beta tile the Streamlit card does", () => {
    const html = renderToStaticMarkup(<Book book={book} rotation={null} />);
    for (const key of ["equity", "duration", "credit", "em"]) {
      expect(html).toContain(`sentiment.beta_${key}<`);
    }
    expect(html).toContain("-0.31");
    // One drift pill each on equity, duration, credit and the bond-
    // correlation tile; EM has no rolling series, so it has none.
    expect(html.match(/sentiment\.drift_pill/g)?.length).toBe(4);
  });
});

// Observed during a Yahoo throttle: the legacy page kept every heading and
// printed the reason with "last attempt hh:mm · source Yahoo Finance", while
// these blocks blanked to a generic "data unavailable". Each block now draws
// the server's `unavailable` itself.
describe("a throttled composite", () => {
  const down: Pulse = {
    ...pulse,
    score: null,
    regime: "unknown",
    components: [],
    missing: [],
    unavailable: "rate_limited",
  };

  it("keeps each block's heading and names the reason and the source", () => {
    for (const html of [
      renderToStaticMarkup(<Composite pulse={down} />),
      renderToStaticMarkup(<Why pulse={down} />),
      renderToStaticMarkup(<Snapshot pulse={down} tables={{ blocks: [] }} />),
    ]) {
      expect(html).toContain("common.rate_limited");
      expect(html).toContain("sentiment.down_stamp");
    }
    expect(renderToStaticMarkup(<Why pulse={down} />)).toContain("sentiment.why_title");
    expect(renderToStaticMarkup(<Composite pulse={down} />)).toContain(
      "sentiment.kicker_pulse",
    );
  });
});

describe("a throttled book", () => {
  const partial: PulseBook = {
    ...book,
    beta: null,
    beta_rolling: null,
    beta_rolling_then: null,
    stance: null,
    bond_correlation: null,
    bond_correlation_then: null,
    betas: [],
    unavailable: "rate_limited",
  };

  it("keeps the weights it could still read, and says why the betas are gone", () => {
    const html = renderToStaticMarkup(<Book book={partial} rotation={null} />);
    expect(html).toContain("sentiment.book_title");
    expect(html).toContain("70%");
    expect(html).toContain("common.rate_limited");
    const side = renderToStaticMarkup(<Side book={partial} regime="unknown" />);
    expect(side).toContain("70%");
    expect(side).toContain("sentiment.down_stamp");
  });

  // A replay nobody could price is not an empty ledger: inviting an import
  // would tell a holder they hold nothing.
  it("does not invite an import when the replay itself failed", () => {
    const empty: PulseBook = {
      ...partial,
      usd_share: null,
      fx_drag: null,
      currency_weights: {},
    };
    for (const html of [
      renderToStaticMarkup(<Book book={empty} rotation={null} />),
      renderToStaticMarkup(<Side book={empty} regime="unknown" />),
    ]) {
      expect(html).not.toContain("sentiment.book_import_cta");
      expect(html).toContain("common.rate_limited");
    }
  });
});
