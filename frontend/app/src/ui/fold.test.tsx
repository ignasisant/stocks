import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Fold } from "./Fold";

const width = (px: number) =>
  vi.stubGlobal("document", {
    querySelector: () => ({ getBoundingClientRect: () => ({ width: px }) }),
  });

const draw = () =>
  renderToStaticMarkup(
    <Fold id="moat" head={<h2>Moat</h2>}>
      <p>body</p>
    </Fold>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Fold", () => {
  it("leaves a desktop section as it was", () => {
    width(1200);
    const html = draw();
    expect(html).not.toContain("<details");
    expect(html).toContain("<h2>Moat</h2><p>body</p>");
  });

  it("folds a phone section to its heading", () => {
    width(380);
    const html = draw();
    expect(html).toContain('<details class="ag-fold">');
    expect(html).toContain('<summary class="ag-fold-head"><h2>Moat</h2></summary>');
    expect(html).not.toContain("body");
  });

  it("opens a section the reader opened before", () => {
    width(380);
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => (key === "ag.fold.moat" ? "1" : null),
    });
    expect(draw()).toContain("<p>body</p>");
  });

  it("opens a section the URL asked for", () => {
    width(380);
    const html = renderToStaticMarkup(
      <Fold id="moat" head={<h2>Moat</h2>} opened>
        <p>body</p>
      </Fold>,
    );
    expect(html).toContain("<p>body</p>");
  });

  it("stays folded when storage is blocked", () => {
    width(380);
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
    });
    expect(draw()).not.toContain("body");
  });
});
