/**
 * The two ways a page says it is waiting: the working line under a press, and
 * the skeleton where a block will land.
 *
 * Both have to be heard as well as seen. A skeleton that was only a grey shape
 * left a screen reader with nothing where the block was coming, and a button
 * that only went disabled said nothing to anybody.
 *
 * Rendered to static markup: the question is what is drawn.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Skeleton } from "../shell/Layout";
import { Status } from "./Status";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("the working line", () => {
  it("is a status that reads its label, with the glyph kept out of it", () => {
    const out = renderToStaticMarkup(<Status label="Deleting every transaction" />);
    expect(out).toContain('role="status"');
    expect(out).toContain("Deleting every transaction");
    expect(out).toMatch(/<span[^>]*aria-hidden="true"[^>]*>✻<\/span>/);
  });
});

describe("the skeleton", () => {
  it("is a status that says it is loading, not a hidden shape", () => {
    const out = renderToStaticMarkup(<Skeleton rows={2} />);
    expect(out).toContain('role="status"');
    expect(out).toContain("common.loading");
    expect(out).not.toMatch(/class="ag-skeleton"[^>]*aria-hidden/);
    expect(out.match(/ag-skeleton-row/g)).toHaveLength(2);
  });
});
