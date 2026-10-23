import { describe, expect, it } from "vitest";
import esm from "../../node_modules/sonner/dist/index.mjs?raw";
import styles from "../../node_modules/sonner/dist/styles.css?raw";
import { stripSonnerInjection } from "../../vite.sonner";

// Sonner appends a <style> at module load; the page's CSP refuses inline
// styles that are not hashed. If an upgrade changes how it does that, this
// fails before the toasts ship unstyled.
describe("sonner under the CSP", () => {
  it("has its runtime CSS injection removed by the build transform", () => {
    const out = stripSonnerInjection(esm);
    expect(out).not.toMatch(/__insertCSS\(["'`]/);
    expect(out.length).toBeLessThan(esm.length);
  });

  it("still ships the same rules as a stylesheet we import", () => {
    expect(styles).toContain("[data-sonner-toaster]");
  });
});
