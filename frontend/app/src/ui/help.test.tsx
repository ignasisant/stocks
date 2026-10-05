/**
 * The "?" beside a label has to be readable without a mouse.
 *
 * There is no DOM in this project's tests, so what is checked is what is
 * drawn (a real button, no native `title` to double up on desktop) and the
 * one decision with arithmetic in it: keeping the panel inside a phone's
 * viewport. Open on tap and dismissal on a touch elsewhere are `useTouchHold`'s
 * contract, covered with the charts that share it; Escape is a key handler on
 * the wrapper.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Help, helpShift } from "./Kpi";

describe("Help", () => {
  const html = renderToStaticMarkup(<Help text="Precio / beneficio" />);

  it("is a button that starts closed and carries no native title", () => {
    expect(html).toContain("<button");
    expect(html).toContain('type="button"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("title=");
    expect(html).not.toContain("ag-kpi-help-pop");
  });

  it("draws nothing without a definition", () => {
    expect(renderToStaticMarkup(<Help text={null} />)).toBe("");
  });
});

describe("helpShift", () => {
  it("leaves a panel that fits where it is", () => {
    expect(helpShift(40, 300, 390)).toBe(0);
  });

  it("pulls a panel back from the right edge", () => {
    expect(helpShift(150, 420, 390)).toBe(-38);
  });

  it("pushes a panel back from the left edge", () => {
    expect(helpShift(-20, 200, 390)).toBe(28);
  });

  it("keeps the start readable when the panel is wider than the screen", () => {
    expect(helpShift(10, 500, 390)).toBe(-2);
  });
});
