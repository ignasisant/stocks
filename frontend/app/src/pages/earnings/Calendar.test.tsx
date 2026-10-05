/**
 * The two dates the calendar adds that belong to no print: the day a loss
 * sold can be bought back, and the Fed / ECB decisions.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key — the figures, though, are formatted for real.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Agenda from "./Agenda";
import { CentralBankChip } from "./CentralBanks";
import type { CentralBankDecision, RepurchaseWindow } from "./data";
import MonthGrid from "./MonthGrid";
import { RepurchaseChip, RepurchaseLegend } from "./Repurchase";

const window: RepurchaseWindow = {
  ticker: "NVDA",
  sell_date: "2026-09-22",
  date: "2026-11-23",
  days_until: 52,
  loss: 101.4,
  currency: "EUR",
  window: "2m",
};

const fed: CentralBankDecision = { bank: "fed", date: "2026-10-28", days_until: 26 };
const ecb: CentralBankDecision = { bank: "ecb", date: "2026-10-29", days_until: 27 };
const far: CentralBankDecision = { bank: "fed", date: "2027-03-17", days_until: 166 };
const gone: CentralBankDecision = { bank: "ecb", date: "2026-09-10", days_until: -22 };

function agenda({
  windows = [],
  banks = [],
}: {
  windows?: RepurchaseWindow[];
  banks?: CentralBankDecision[];
}) {
  return renderToStaticMarkup(
    <Agenda
      events={[]}
      deadlines={[]}
      windows={windows}
      banks={banks}
      dividends={[]}
    />,
  );
}

function grid(month: number) {
  return renderToStaticMarkup(
    <MonthGrid
      year={2026}
      month={month}
      now="2026-10-02"
      events={[]}
      results={[]}
      deadlines={[]}
      windows={[window]}
      banks={[gone, fed, ecb, far]}
      dividends={[]}
      onPick={() => {}}
    />,
  );
}

describe("buy-back windows", () => {
  it("land on the first free day, as a chip that opens its explanation", () => {
    expect(grid(11).match(/earn-chip rebuy/g)).toHaveLength(1);
    expect(grid(10)).not.toContain("earn-chip rebuy");
    const chip = renderToStaticMarkup(
      <RepurchaseChip window={window} onPick={() => {}} />,
    );
    expect(chip).toContain("earnings.rebuy_title");
    expect(chip).toMatch(/^<button type="button"/);
    expect(chip).not.toContain("href");
  });

  it("list the ticker, the day it frees up and the loss at stake", () => {
    const html = agenda({ windows: [window] });
    expect(html).toContain("NVDA");
    expect(html).toContain("101.40");
    expect(html).toContain("earnings.mon_11");
  });

  it("say nothing where there is nothing to wait for", () => {
    expect(agenda({})).toBe("");
    expect(renderToStaticMarkup(<RepurchaseLegend windows={[]} />)).toBe("");
  });
});

describe("rate decisions", () => {
  it("draw a chip per bank on its day", () => {
    const html = grid(10);
    expect(html.match(/earn-chip cb/g)).toHaveLength(2);
    expect(
      renderToStaticMarkup(<CentralBankChip decision={ecb} onPick={() => {}} />),
    ).toContain("earnings.cb_ecb");
  });

  it("list only what is ahead, one week at a time", () => {
    const html = agenda({ banks: [gone, fed, ecb, far] });
    // fed and ecb share a week; the past one is gone, the far one is a week of its own.
    expect(html.match(/earn-week-h/g)).toHaveLength(2);
    expect(html.match(/earnings\.cb_/g)).toHaveLength(3);
    expect(agenda({ banks: [gone] })).toBe("");
  });
});

describe("a busy day", () => {
  const prints = ["AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "NVDA"].map(
    (ticker) => ({ ticker, date: "2026-10-28", days_until: 26 }),
  );

  function busy(events: typeof prints) {
    return renderToStaticMarkup(
      <MonthGrid
        year={2026}
        month={10}
        now="2026-10-02"
        events={events}
        results={[]}
        deadlines={[]}
        windows={[]}
        banks={[]}
        dividends={[]}
        onPick={() => {}}
      />,
    );
  }

  it("folds past five chips behind +N, so one cell cannot stretch its row", () => {
    const html = busy(prints);
    expect(html.match(/class="earn-chip/g)).toHaveLength(4);
    expect(html).toContain('class="earn-more"');
    expect(html).toContain("earnings.chips_more");
    expect(html).toContain('aria-expanded="false"');
  });

  it("draws five in full rather than hiding one behind a button", () => {
    const html = busy(prints.slice(0, 5));
    expect(html.match(/class="earn-chip/g)).toHaveLength(5);
    expect(html).not.toContain("earn-more");
  });

  it("marks today on the day number, not by filling the cell", () => {
    expect(busy([])).toContain('class="earn-day today"');
  });
});
