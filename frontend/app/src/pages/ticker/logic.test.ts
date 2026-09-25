/**
 * The page's pure logic — the rules that are wrong silently rather than loudly.
 *
 * Not the components: what is tested here is arithmetic and wording that no
 * screenshot would catch. A yield priced against the wrong close, a CAGR drawn
 * between a loss and a profit, an alert sent with the field its type does not
 * use — each of those renders perfectly and means something else.
 *
 * The translator is the real one over the real English strings: a stub that
 * dropped the placeholders would pass while the page printed "{pct}".
 */

import { describe, expect, it } from "vitest";

import { complete, draft, num, payload, summary } from "./alerts";
import { dividendLine, resultsLines, snap } from "./events";
import {
  barGrowth,
  compact,
  growthLabel,
  insiderPrice,
  insiderValue,
  legend,
  orElse,
  signed,
  yoy,
} from "./format";
import type { AlertForm } from "./types";

const CATALOG: Record<string, string> = {
  "ticker.hover_dividend": "<b>Dividend</b>  {amt}/sh \u00b7 ex-date {date}",
  "ticker.hover_div_yield": " \u00b7 \u2248{pct}% of price",
  "ticker.hover_results": "<b>Results</b> \u00b7 {date}",
  "ticker.hover_vs_est": " vs est {est}",
  "ticker.hover_surprise": "surprise",
  "ticker.hover_move": "move {pct}% across print",
  "ticker.legend_latest": "{label} \u00b7 {val} latest",
  "ticker.legend_cagr": "{pct}%/yr CAGR",
};

/** `shell/i18n`'s lookup, reduced to what these functions use. */
const t = (key: string, values?: Record<string, string | number>): string => {
  const template = CATALOG[key] ?? key;
  return values
    ? template.replace(/\{(\w+)\}/g, (whole, name: string) =>
        name in values ? String(values[name]) : whole,
      )
    : template;
};

const PRICE: AlertForm = { type: "above", field: "price", default: null, window: null };
const PCT: AlertForm = { type: "drawdown", field: "pct", default: 5, window: null };
const RSI: AlertForm = { type: "rsi_below", field: "level", default: 30, window: 14 };
const CROSS: AlertForm = { type: "sma_cross", field: null, default: null, window: 50 };

describe("growth", () => {
  it("measures against the magnitude of the base", () => {
    // The whole reason this is not `cur / prev - 1`: a loss deepening from
    // -56 to -187 reads +233% once the two negatives cancel.
    expect(yoy(-187, -56)).toBeCloseTo(-233.9, 1);
    expect(yoy(56, -56)).toBeCloseTo(200, 6);
  });

  it("is null when there is no usable base", () => {
    expect(yoy(10, 0)).toBeNull();
    expect(yoy(10, null)).toBeNull();
    expect(yoy(null, 10)).toBeNull();
  });

  it("prints nothing rather than a zero when there is no figure", () => {
    expect(growthLabel(null)).toBe("");
    expect(growthLabel(0)).toBe("+0%");
    expect(growthLabel(-12.4)).toBe("-12%");
  });
});

describe("per-bar growth on the results chart", () => {
  it("anchors the first forecast on the last reported year with a value", () => {
    // Reported 100, gap, 120; forecast 132, 145. The year after the gap has no
    // label (a gap stays a gap), and the first forecast is measured against
    // 120 — not against the hole, and not against nothing.
    const out = barGrowth([100, null, 120, 132, 145.2], 3);
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(out[2]).toBeNull();
    expect(out[3]).toBeCloseTo(10, 6);
    expect(out[4]).toBeCloseTo(10, 6);
  });

  it("keeps the legend on filed years only", () => {
    // What the chart passes: the reported slice. A consensus tail of 500
    // must not become the "latest" revenue.
    const values = [100, 200, 500];
    expect(legend("Revenue", values.slice(0, 2), t)).toBe(
      "Revenue \u00b7 200 latest \u00b7 +100%/yr CAGR",
    );
  });
});

describe("insider table cells", () => {
  it("prints Streamlit's spelling, and nothing when there is no figure", () => {
    expect(insiderValue(-474813, "USD")).toBe("$-474,813");
    expect(insiderValue(12000, "EUR")).toBe("€+12,000");
    expect(insiderPrice(330.19, "USD")).toBe("$330.19");
    expect(insiderPrice(null, "USD")).toBe("");
    expect(insiderValue(null, "USD")).toBe("");
  });
});

describe("signs and sizes", () => {
  it("always signs a change", () => {
    expect(signed(3.5)).toBe("+3.50");
    expect(signed(-3.5)).toBe("-3.50");
    // Zero is not a fall.
    expect(signed(0)).toBe("+0.00");
  });

  it("shortens a figure the way an axis does", () => {
    expect(compact(391_000_000_000)).toBe("391B");
    expect(compact(-2_400_000)).toBe("-2.40M");
    expect(compact(null)).toBe("\u2014");
  });
});

describe("the results legend", () => {
  it("carries the latest figure and the rate that got there", () => {
    // 100 -> 121 over three points is two years of +10%.
    const name = legend("Revenue", [100e9, 110e9, 121e9], t);
    expect(name).toContain("121B");
    expect(name).toContain("+10");
  });

  it("drops the rate when the span crosses zero", () => {
    // A CAGR from a loss to a profit is arithmetic, not information.
    expect(legend("Net income", [-50e6, 20e6], t)).not.toContain("CAGR");
  });

  it("is just the label when nothing was reported", () => {
    expect(legend("Revenue", [null, null], t)).toBe("Revenue");
  });
});

describe("a string the API named", () => {
  it("falls back to what the API sent when no catalog has it", () => {
    // A KPI tile with no string yet reads "Enterprise value", not the key.
    expect(orElse(t, "ticker.kpi_nope", "Enterprise value")).toBe("Enterprise value");
    expect(orElse(t, "ticker.hover_surprise", "fallback")).toBe("surprise");
  });
});

describe("what a corporate-event marker says", () => {
  it("prices a dividend against the close of ITS day", () => {
    // Not today's: a 2019 dividend told as a percentage of the 2026 price is
    // a different number, and a plausible-looking one.
    const line = dividendLine(0.24, 46.0, "2019-05-10", t);
    expect(line.text).toContain("0.52%");
    expect(line.text).toContain("2019-05-10");
  });

  it("says nothing about yield when the close is missing", () => {
    expect(dividendLine(0.24, null, "2019-05-10", t).text).not.toContain("%");
  });

  it("reads a beat and the move across the print", () => {
    const event = {
      date: "2024-05-02",
      eps_estimate: 1.5,
      reported_eps: 1.53,
      surprise_pct: 2.0,
      beat: true,
    };
    const lines = resultsLines(event, [100, 102, 108], 1, true, t);
    const text = lines.map((line) => line.text).join(" | ");
    expect(text).toContain("EPS 1.53");
    expect(text).toContain("+2.0%");
    // Session before to session after: 100 -> 108.
    expect(text).toContain("+8.0");
    // A beat is green, a miss red — the tone rides the line, not the label.
    expect(lines.some((line) => line.tone === "up")).toBe(true);
  });

  it("leaves the move out on a range whose bars are not days", () => {
    const event = {
      date: "2024-05-02",
      eps_estimate: null,
      reported_eps: null,
      surprise_pct: null,
      beat: null,
    };
    const lines = resultsLines(event, [100, 102, 108], 1, false, t);
    expect(lines.map((line) => line.text).join(" ")).not.toContain("across");
  });

  it("puts a report filed on a closed day on the next bar", () => {
    const days = ["2024-05-01", "2024-05-02", "2024-05-06"];
    expect(snap(days, "2024-05-04")).toBe(2);
    expect(snap(days, "2024-05-02")).toBe(1);
    // Past the end: the last bar, never -1 read as "the last element".
    expect(snap(days, "2025-01-01")).toBe(2);
  });
});

describe("how an alert rule reads back", () => {
  it("prints what the type actually carries, and nothing else", () => {
    expect(summary({ type: "above", price: 120.5 }, t)).toBe(
      "widgets.alert_t_above 120.5",
    );
    expect(summary({ type: "drawdown", pct: 5, window: 252 }, t)).toBe(
      "widgets.alert_t_drawdown 5% (252d)",
    );
  });

  it("drops the trailing zeros the app drops", () => {
    // Python's %g, which is what the app's summary uses.
    expect(num(5)).toBe("5");
    expect(num(120.5)).toBe("120.5");
    expect(num(0.1 + 0.2)).toBe("0.3");
  });
});

describe("a draft of a new rule", () => {
  it("prefills what the server says to prefill", () => {
    expect(draft(PCT)).toEqual({ type: "drawdown", pct: 5 });
    expect(draft(RSI)).toEqual({ type: "rsi_below", level: 30, window: 14 });
    expect(draft(CROSS)).toEqual({ type: "sma_cross", window: 50 });
  });

  it("starts a price empty rather than at a number nobody chose", () => {
    expect(draft(PRICE)).toEqual({ type: "above", price: 0 });
  });
});

describe("what is worth sending", () => {
  it("refuses a zero threshold", () => {
    // No price is ever below 0, and a 0% move fires on every tick.
    expect(complete(PRICE, { type: "above", price: 0 })).toBe(false);
    expect(complete(PCT, { type: "drawdown", pct: 0 })).toBe(false);
    expect(complete(PRICE, { type: "above", price: 120 })).toBe(true);
  });

  it("lets through the types that ask for no number", () => {
    expect(complete(CROSS, draft(CROSS))).toBe(true);
  });

  it("carries only the field this type uses", () => {
    // The editor's draft can hold leftovers from a type the reader picked and
    // changed; sending a price on a drawdown rule stores a rule that is never
    // evaluated on it.
    const stale = { type: "drawdown", pct: 8, price: 120, level: 30 };
    expect(payload(PCT, stale)).toEqual({ type: "drawdown", pct: 8 });
  });

  it("keeps the window, which is a field of its own", () => {
    expect(payload(RSI, { type: "rsi_below", level: 25, window: 20 })).toEqual({
      type: "rsi_below",
      level: 25,
      window: 20,
    });
  });
});
