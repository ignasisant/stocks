import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { attachAssistant } from "../../shell/assistant";
import { fileOf } from "./ToAssistant";

vi.mock("../../shell/i18n", () => ({ useT: () => (k: string) => k }));

describe("fileOf", () => {
  it("gives a staged statement back as the bytes it was", async () => {
    const text = "date,ticker\n2024-01-02,AAPL\n";
    const file = fileOf({
      filename: "trades.csv",
      content: btoa(text),
      bytes: text.length,
    });
    expect(file.name).toBe("trades.csv");
    expect(await file.text()).toBe(text);
  });
});

describe("ToAssistant", () => {
  it("draws nothing, and hands nothing over, with no drawer listening", async () => {
    const { ToAssistant } = await import("./ToAssistant");
    // A guest's locked drawer cannot import: the button would be a dead end.
    expect(
      renderToStaticMarkup(
        <ToAssistant accepts={["csv"]} onHanded={() => {}} staged={null} />,
      ),
    ).toBe("");
    expect(() => attachAssistant(new File(["x"], "a.csv"))).not.toThrow();
  });
});
