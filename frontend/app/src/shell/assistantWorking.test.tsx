/**
 * The phone tab bar's Assistant item says when the shut drawer is working:
 * one flag, set by the drawer, read by the bar.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { setAssistantWorking, useAssistantWorking } from "./assistant";

afterEach(() => setAssistantWorking(false));

describe("the assistant's working flag", () => {
  it("is quiet by default", () => {
    expect(useAssistantWorking).toBeTypeOf("function");
    setAssistantWorking(false);
    expect(renderToStaticMarkup(<Probe />)).toBe("idle");
  });

  it("reads true while the drawer says so (server snapshot stays idle)", () => {
    setAssistantWorking(true);
    // Server rendering uses the idle snapshot: the flag only paints in a browser.
    expect(renderToStaticMarkup(<Probe />)).toBe("idle");
  });
});

function Probe() {
  return <>{useAssistantWorking() ? "working" : "idle"}</>;
}
